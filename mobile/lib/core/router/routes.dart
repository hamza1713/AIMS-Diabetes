/// Route paths. Comments map each route to its Figma frame.
abstract final class Routes {
  // Auth
  static const login = '/login'; // 01 · Login
  static const signUp = '/sign-up'; // 01b · Sign Up
  static const forgotPassword = '/forgot-password'; // 01c · Forgot Password

  // Bottom-nav tabs
  static const home = '/home'; // Home Dashboard
  static const chat = '/chat'; // 02 · AI Chat
  static const track = '/track'; // 04 · Health Tracking
  static const profile = '/profile'; // 05 · Profile

  // Home children
  static const notifications = '/home/notifications'; // 16
  static const analytics = '/home/analytics'; // 13

  // Tracking children
  static const glucose = '/track/glucose'; // 06
  static const addGlucose = '/track/glucose/add'; // 17
  static const meals = '/track/meals'; // 07
  static const addMeal = '/track/meals/add'; // 18
  static const visionAi = '/track/meals/scan'; // 11
  static const exercise = '/track/exercise'; // 08
  static const logWorkout = '/track/exercise/add'; // 19
  static const water = '/track/water'; // 09
  static const addWater = '/track/water/add'; // 20
  static const medications = '/track/medications'; // 10
  static const addMedication = '/track/medications/add'; // 21

  // Risk assessment flow
  static const riskIntro = '/risk'; // RA0 · Risk Intro
  static const riskQuiz = '/risk/quiz'; // RA1–RA7
  static const riskResult = '/risk/result'; // 12 · Risk Results

  // Profile children
  static const editProfile = '/profile/edit'; // 14
  static const settings = '/profile/settings'; // 15
}
