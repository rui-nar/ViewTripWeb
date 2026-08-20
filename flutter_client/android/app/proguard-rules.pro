# R8 rules for the release build (see build.gradle.kts: isMinifyEnabled/isShrinkResources).
# The Flutter Gradle plugin keeps the engine's own io.flutter.** classes automatically;
# everything below is for app dependencies R8 can't reason about on its own.

# Flutter's deferred-components support references Play Core split-install
# classes even though this app doesn't use deferred components, which makes R8
# fail the build with "Missing class com.google.android.play.core...".
# Recommended by https://docs.flutter.dev/deployment/android#build-errors-with-play-core-library
-dontwarn com.google.android.play.core.splitcompat.SplitCompatApplication
-dontwarn com.google.android.play.core.splitinstall.SplitInstallException
-dontwarn com.google.android.play.core.splitinstall.SplitInstallManager
-dontwarn com.google.android.play.core.splitinstall.SplitInstallManagerFactory
-dontwarn com.google.android.play.core.splitinstall.SplitInstallRequest$Builder
-dontwarn com.google.android.play.core.splitinstall.SplitInstallRequest
-dontwarn com.google.android.play.core.splitinstall.SplitInstallSessionState
-dontwarn com.google.android.play.core.splitinstall.SplitInstallStateUpdatedListener
-dontwarn com.google.android.play.core.tasks.OnFailureListener
-dontwarn com.google.android.play.core.tasks.OnSuccessListener
-dontwarn com.google.android.play.core.tasks.Task

# Plugins bind Java/Kotlin methods to native (JNI) code by class/method
# signature (geolocator, cryptography_plus, vector_tile_renderer). R8 can't see
# those JNI call sites, so without this it's free to rename or strip the Java
# side and break the binding at runtime.
-keepclasseswithmembers class * {
    native <methods>;
}
