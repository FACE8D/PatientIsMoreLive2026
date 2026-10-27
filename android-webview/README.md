# Android WebView wrapper source

This is the source scaffold for the Android wrapper; it is not a signed APK and does not include project-specific Firebase credentials.

## Configure and build

1. Install JDK 17 and Android Studio / Android SDK 35.
2. Set the backend URL in Gradle:
   - Emulator: `./gradlew assembleDebug -PwebviewBaseUrl=http://10.0.2.2:8765/`
   - HTTPS deployment: `./gradlew assembleDebug -PwebviewBaseUrl=https://your-deployment.example/`
3. For push, register the Android app in your Firebase project and copy that project's `google-services.json` to `app/google-services.json`. Never commit this file to public source.
4. Configure `FIREBASE_SERVICE_ACCOUNT_JSON` on the server with restricted credentials. The server endpoint stores the FCM token only after the user logs in and the in-app WebView bridge registers it.
5. Build/sign for distribution using your organisation's Android signing process.

## Important deployment note

The manifest permits cleartext HTTP only to support a local emulator demo. This is not acceptable for patient data. For any shared environment, require HTTPS, remove `android:usesCleartextTraffic="true"`, configure a production domain, and test authentication, cookie behaviour, notification permission, deep links, and FCM delivery. Do not use demo credentials in production.

The app still depends on the Python service being deployed and reachable. This project is a WebView shell plus optional Firebase Messaging service, not a fully offline native application. Notifications are non-emergency and are not guaranteed to be delivered/read.
