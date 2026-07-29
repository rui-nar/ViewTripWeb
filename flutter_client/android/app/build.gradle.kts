import java.io.FileInputStream
import java.util.Properties
import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    id("com.android.application")
    id("kotlin-android")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

// Release signing material, kept out of the repo (see android/.gitignore).
// Locally: created by scripts/new-android-keystore.ps1.
// In CI:   written by .github/workflows/android-release.yml from secrets.
// When the file is absent the release build falls back to the debug key, so
// `flutter run --release` still works on a machine that has no keystore — such
// a build is only installable by hand, never published.
val keystorePropertiesFile = rootProject.file("key.properties")
val keystoreProperties = Properties().apply {
    if (keystorePropertiesFile.exists()) {
        FileInputStream(keystorePropertiesFile).use { load(it) }
    }
}
val hasReleaseKeystore = keystorePropertiesFile.exists()

android {
    namespace = "com.traxjourney.app"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_21
        targetCompatibility = JavaVersion.VERSION_21
    }

    defaultConfig {
        // Permanent app identity: changing it after publication orphans every
        // installed copy, and both the Google OAuth client and the App Links
        // assetlinks.json entry are bound to this exact string.
        applicationId = "com.traxjourney.app"
        minSdk = flutter.minSdkVersion
        targetSdk = flutter.targetSdkVersion
        // versionCode comes from --build-number, which CI derives from the tag
        // (scripts/android_version_code.py); versionName from --build-name.
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    signingConfigs {
        if (hasReleaseKeystore) {
            create("release") {
                keyAlias = keystoreProperties.getProperty("keyAlias")
                keyPassword = keystoreProperties.getProperty("keyPassword")
                storeFile = file(keystoreProperties.getProperty("storeFile"))
                storePassword = keystoreProperties.getProperty("storePassword")
            }
        }
    }

    buildTypes {
        release {
            signingConfig = if (hasReleaseKeystore) {
                signingConfigs.getByName("release")
            } else {
                signingConfigs.getByName("debug")
            }
        }
    }
}

// Replaces the android.kotlinOptions block, which the Kotlin Gradle plugin
// deprecates from 2.x and AGP 9 rejects outright. Must stay in step with
// compileOptions above.
kotlin {
    compilerOptions {
        jvmTarget = JvmTarget.JVM_21
    }
}

flutter {
    source = "../.."
}
