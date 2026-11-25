import 'package:cached_network_image/cached_network_image.dart';
import 'package:flutter/material.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/widgets/state_views.dart';
import '../application/chat_controller.dart';
import '../data/chat_models.dart';

/// Figma "02 · AI Chat", "22 · AI Thinking State", "DARK · AI Chat".
class ChatScreen extends ConsumerStatefulWidget {
  const ChatScreen({super.key});

  @override
  ConsumerState<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends ConsumerState<ChatScreen> {
  final _input = TextEditingController();
  final _scroll = ScrollController();

  static const _suggestions = [
    'What is a normal fasting glucose?',
    'How does metformin work?',
    'Best snacks for stable blood sugar',
    'Signs of hypoglycemia',
  ];

  @override
  void dispose() {
    _input.dispose();
    _scroll.dispose();
    super.dispose();
  }

  void _send([String? text]) {
    final q = text ?? _input.text;
    if (q.trim().isEmpty) return;
    _input.clear();
    ref.read(chatControllerProvider.notifier).send(q);
  }

  void _scrollToEnd() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scroll.hasClients) {
        _scroll.animateTo(_scroll.position.maxScrollExtent,
            duration: const Duration(milliseconds: 200), curve: Curves.easeOut);
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final messages = ref.watch(chatControllerProvider);
    final streaming = messages.isNotEmpty && messages.last.streaming;
    ref.listen(chatControllerProvider, (_, _) => _scrollToEnd());

    return Scaffold(
      appBar: AppBar(
        title: Row(
          children: [
            const CircleAvatar(
              radius: 18,
              backgroundColor: AppColors.primary,
              child: Icon(Icons.auto_awesome_rounded, color: Colors.white, size: 18),
            ),
            const SizedBox(width: AppSpacing.md),
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text('AI Assistant'),
                Text('Answers from clinical research',
                    style: Theme.of(context).textTheme.bodySmall),
              ],
            ),
          ],
        ),
        actions: [
          if (messages.isNotEmpty)
            IconButton(
              tooltip: 'New chat',
              icon: const Icon(Icons.refresh_rounded),
              onPressed: () => ref.read(chatControllerProvider.notifier).clear(),
            ),
        ],
      ),
      body: Column(
        children: [
          Expanded(
            child: messages.isEmpty
                ? _EmptyChat(suggestions: _suggestions, onTap: _send)
                : ListView.builder(
                    controller: _scroll,
                    padding: const EdgeInsets.all(AppSpacing.page),
                    itemCount: messages.length,
                    itemBuilder: (_, i) => _MessageBubble(messages[i]),
                  ),
          ),
          _Composer(
            controller: _input,
            streaming: streaming,
            onSend: _send,
            onStop: () => ref.read(chatControllerProvider.notifier).stop(),
          ),
        ],
      ),
    );
  }
}

class _EmptyChat extends StatelessWidget {
  const _EmptyChat({required this.suggestions, required this.onTap});
  final List<String> suggestions;
  final ValueChanged<String> onTap;

  @override
  Widget build(BuildContext context) => ListView(
        padding: const EdgeInsets.all(AppSpacing.page),
        children: [
          const EmptyStateView(
            icon: Icons.auto_awesome_rounded,
            title: 'Ask me anything about diabetes',
            message:
                'Answers are grounded in clinical research papers, with sources. '
                'This is not a substitute for medical advice.',
          ),
          Wrap(
            spacing: AppSpacing.sm,
            runSpacing: AppSpacing.sm,
            alignment: WrapAlignment.center,
            children: [
              for (final s in suggestions)
                ActionChip(label: Text(s), onPressed: () => onTap(s)),
            ],
          ),
        ],
      );
}

class _MessageBubble extends StatelessWidget {
  const _MessageBubble(this.message);
  final ChatMessage message;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    final isUser = message.role == ChatRole.user;
    final maxWidth = MediaQuery.sizeOf(context).width * 0.82;

    final bubble = Container(
      constraints: BoxConstraints(maxWidth: maxWidth),
      margin: const EdgeInsets.only(bottom: AppSpacing.md),
      padding: const EdgeInsets.all(AppSpacing.md),
      decoration: BoxDecoration(
        color: isUser
            ? AppColors.primary
            : message.isError
                ? AppColors.danger.withValues(alpha: 0.1)
                : p.surface,
        border: isUser ? null : Border.all(color: p.border),
        borderRadius: BorderRadius.only(
          topLeft: const Radius.circular(AppRadius.lg),
          topRight: const Radius.circular(AppRadius.lg),
          bottomLeft: Radius.circular(isUser ? AppRadius.lg : 4),
          bottomRight: Radius.circular(isUser ? 4 : AppRadius.lg),
        ),
      ),
      child: isUser
          ? Text(message.content, style: const TextStyle(color: Colors.white))
          : message.isThinking
              ? _Thinking(status: message.status)
              : MarkdownBody(
                  data: message.content,
                  selectable: true,
                  styleSheet: MarkdownStyleSheet.fromTheme(Theme.of(context)),
                ),
    );

    return Align(
      alignment: isUser ? Alignment.centerRight : Alignment.centerLeft,
      child: Column(
        crossAxisAlignment:
            isUser ? CrossAxisAlignment.end : CrossAxisAlignment.start,
        children: [
          bubble,
          if (message.sources.isNotEmpty && !message.isThinking)
            _Sources(message.sources),
        ],
      ),
    );
  }
}

/// Figma "22 · AI Thinking State": animated dots + live status line.
class _Thinking extends StatelessWidget {
  const _Thinking({this.status});
  final String? status;

  @override
  Widget build(BuildContext context) => Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          const SizedBox(
            width: 16,
            height: 16,
            child: CircularProgressIndicator(strokeWidth: 2),
          ),
          const SizedBox(width: AppSpacing.md),
          Flexible(
            child: Text(status ?? 'Thinking…',
                style: Theme.of(context).textTheme.bodySmall),
          ),
        ],
      );
}

class _Sources extends StatelessWidget {
  const _Sources(this.sources);
  final List<ChatSource> sources;

  @override
  Widget build(BuildContext context) {
    final p = context.palette;
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.lg),
      child: SizedBox(
        height: 84,
        child: ListView.separated(
          scrollDirection: Axis.horizontal,
          itemCount: sources.length.clamp(0, 6),
          separatorBuilder: (_, _) => const SizedBox(width: AppSpacing.sm),
          itemBuilder: (context, i) {
            final s = sources[i];
            return InkWell(
              borderRadius: BorderRadius.circular(AppRadius.md),
              onTap: s.absoluteImageUrl == null
                  ? null
                  : () => _showPage(context, s),
              child: Container(
                width: 220,
                padding: const EdgeInsets.all(AppSpacing.sm),
                decoration: BoxDecoration(
                  color: p.primarySoft,
                  borderRadius: BorderRadius.circular(AppRadius.md),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        const Icon(Icons.description_outlined,
                            size: 14, color: AppColors.primary),
                        const SizedBox(width: 4),
                        Text('Source ${i + 1}',
                            style: const TextStyle(
                                fontSize: 11,
                                color: AppColors.primary,
                                fontWeight: FontWeight.w600)),
                      ],
                    ),
                    const SizedBox(height: 4),
                    Text(s.title,
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                            fontSize: 12, fontWeight: FontWeight.w600)),
                    const Spacer(),
                    Text(s.citation,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: Theme.of(context).textTheme.bodySmall),
                  ],
                ),
              ),
            );
          },
        ),
      ),
    );
  }

  void _showPage(BuildContext context, ChatSource s) {
    showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (_) => DraggableScrollableSheet(
        expand: false,
        initialChildSize: 0.85,
        builder: (_, scroll) => ListView(
          controller: scroll,
          padding: const EdgeInsets.all(AppSpacing.page),
          children: [
            Text(s.title, style: Theme.of(context).textTheme.titleMedium),
            if (s.authors != null)
              Text(s.authors!, style: Theme.of(context).textTheme.bodySmall),
            const SizedBox(height: AppSpacing.md),
            InteractiveViewer(
              child: CachedNetworkImage(
                imageUrl: s.absoluteImageUrl!,
                placeholder: (_, _) => const SizedBox(
                    height: 300, child: Center(child: CircularProgressIndicator())),
                errorWidget: (_, _, _) =>
                    const Text('Page preview not available.'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _Composer extends StatelessWidget {
  const _Composer({
    required this.controller,
    required this.streaming,
    required this.onSend,
    required this.onStop,
  });

  final TextEditingController controller;
  final bool streaming;
  final VoidCallback onSend;
  final VoidCallback onStop;

  @override
  Widget build(BuildContext context) => SafeArea(
        top: false,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(
              AppSpacing.page, AppSpacing.sm, AppSpacing.page, AppSpacing.md),
          child: Row(
            children: [
              Expanded(
                child: TextField(
                  controller: controller,
                  minLines: 1,
                  maxLines: 4,
                  textInputAction: TextInputAction.send,
                  onSubmitted: (_) => onSend(),
                  decoration: InputDecoration(
                    hintText: 'Ask about diabetes…',
                    border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(AppRadius.pill),
                    ),
                  ),
                ),
              ),
              const SizedBox(width: AppSpacing.sm),
              IconButton.filled(
                style: IconButton.styleFrom(
                  backgroundColor: AppColors.primary,
                  minimumSize: const Size(48, 48),
                ),
                onPressed: streaming ? onStop : onSend,
                icon: Icon(streaming ? Icons.stop_rounded : Icons.arrow_upward_rounded),
              ),
            ],
          ),
        ),
      );
}
