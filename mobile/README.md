# AIMS Diabetes — Flutter app

The mobile client for AIMS Diabetes. See the [root README](../README.md) for the full project, and the [user guide](../docs/USER_GUIDE.md) for how each screen works.

## Run

```bash
flutter pub get
flutter run                                                   # emulator / simulator
flutter run --dart-define=API_BASE_URL=http://192.168.1.10:8000   # physical device on your LAN
```

Defaults for `API_BASE_URL`: Android emulator `http://10.0.2.2:8000`; iOS simulator and web `http://127.0.0.1:8000`.

## Structure

```text
lib/
├── core/
│   ├── config/env.dart            API base URL
│   ├── network/                   Dio client + JWT refresh interceptor, SSE client, connectivity
│   ├── router/                    routes (mapped to Figma frames) and auth redirect
│   ├── theme/                     colour tokens, spacing, light/dark ThemeData
│   ├── utils/                     lenient JSON readers, formatting
│   └── widgets/                   shell (bottom nav + quick add), cards, charts, forms, states
└── features/
    ├── auth/                      login, sign-up, forgot password
    ├── home/                      dashboard
    ├── chat/                      streaming AI assistant
    ├── tracking/                  glucose, meals, Vision AI, exercise, water, medications
    ├── risk/                      CDC risk test (scored on device + saved on server)
    ├── analytics/                 monthly summary
    ├── profile/                   profile, edit profile, settings
    └── notifications/
```

Each feature talks to the backend only through its `data/*_repository.dart`, so API changes stay in one place.

## Quality

```bash
flutter analyze
flutter test
```

## Design

All colours come from `lib/core/theme/app_colors.dart` (`AppColors` and the theme-aware `AppPalette`). Update the tokens there to match the Figma variables; every screen follows.
