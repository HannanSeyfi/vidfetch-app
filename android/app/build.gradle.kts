import groovy.json.JsonSlurper
import java.io.File
import java.net.URI
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.security.MessageDigest

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
}

val releaseKeystore = System.getenv("VIDFETCH_KEYSTORE_FILE")
val emulatorBuild = providers.gradleProperty("emulatorBuild").orNull == "true"
val extractorOutput = layout.buildDirectory.dir("generated/extractor")
val prepareExtractorRuntime = tasks.register("prepareExtractorRuntime") {
    val lockFile = rootProject.file("runtime/runtime-lock.json")
    inputs.file(lockFile)
    outputs.dir(extractorOutput)
    doLast {
        val lock = JsonSlurper().parse(lockFile) as Map<*, *>
        for (entry in lock["artifacts"] as List<*>) {
            val artifact = entry as Map<*, *>
            val target = extractorOutput.get().file(artifact["path"] as String).asFile
            val expected = artifact["sha256"] as String
            fun checksum(file: File): String {
                val digest = MessageDigest.getInstance("SHA-256")
                file.inputStream().use { input ->
                    val buffer = ByteArray(65536)
                    while (true) {
                        val count = input.read(buffer)
                        if (count < 0) break
                        digest.update(buffer, 0, count)
                    }
                }
                return digest.digest().joinToString("") { "%02x".format(it) }
            }
            if (target.exists() && checksum(target) == expected) continue
            target.parentFile.mkdirs()
            val temporary = File(target.parentFile, "${target.name}.download")
            try {
                val connection = URI(artifact["url"] as String).toURL().openConnection().apply {
                    connectTimeout = 30000
                    readTimeout = 120000
                }
                connection.getInputStream().use { input -> temporary.outputStream().use(input::copyTo) }
                check(checksum(temporary) == expected) { "Runtime checksum mismatch: ${artifact["path"]}" }
                Files.move(temporary.toPath(), target.toPath(), StandardCopyOption.REPLACE_EXISTING)
            } finally {
                temporary.delete()
            }
        }
    }
}
tasks.named("preBuild").configure { dependsOn(prepareExtractorRuntime) }

android {
    namespace = "com.vidfetch.app"
    compileSdk = 36
    buildToolsVersion = "36.0.0"
    defaultConfig {
        applicationId = "com.vidfetch.app"
        minSdk = 24
        targetSdk = 36
        versionCode = 12
        versionName = "0.3.0"
        buildConfigField("String", "BUNDLED_YTDLP_VERSION", "\"2026.10.10.233141\"")
        buildConfigField("String", "RUNTIME_COMMIT", "\"35f2609d80ce26b6683a0b2b6bc52f32efe4c81c\"")
        testInstrumentationRunner = "com.vidfetch.app.data.extractor.ExtractorInstrumentationRunner"
    }
    buildFeatures { compose = true; buildConfig = true }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    sourceSets["main"].apply {
        jniLibs.srcDir(extractorOutput.map { it.dir("jni") })
        res.srcDir(extractorOutput.map { it.dir("res") })
    }
    packaging {
        jniLibs {
            useLegacyPackaging = true
            keepDebugSymbols += "**/*.so"
            excludes += if (emulatorBuild) listOf("**/arm64-v8a/**", "**/armeabi-v7a/**", "**/x86/**") else listOf("**/x86_64/**", "**/x86/**")
        }
    }
    splits {
        abi {
            isEnable = true
            reset()
            if (emulatorBuild) include("x86_64") else include("arm64-v8a", "armeabi-v7a")
            isUniversalApk = false
        }
    }
    signingConfigs {
        if (releaseKeystore != null) {
            create("release") {
                storeFile = file(releaseKeystore)
                storePassword = System.getenv("VIDFETCH_KEYSTORE_PASSWORD")
                keyAlias = System.getenv("VIDFETCH_KEY_ALIAS")
                keyPassword = System.getenv("VIDFETCH_KEY_PASSWORD")
            }
        }
    }
    buildTypes {
        release {
            signingConfig = signingConfigs.findByName("release") ?: signingConfigs.getByName("debug")
            // The embedded yt-dlp/Python/FFmpeg runtime is loaded dynamically. Keep the release
            // bytecode unshrunk until explicit keep rules are validated on a physical device.
            isMinifyEnabled = false
            isShrinkResources = false
        }
    }
}

kotlin {
    compilerOptions {
        jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime)
    implementation(libs.androidx.lifecycle.viewmodel)
    implementation(libs.androidx.activity.compose)
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.ui)
    implementation(libs.androidx.ui.graphics)
    implementation(libs.androidx.ui.tooling.preview)
    implementation(libs.androidx.material3)
    implementation(libs.androidx.material.icons)
    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.coil.compose)
    implementation(libs.coil.video)
    testImplementation(libs.junit)
    androidTestImplementation(libs.junit)
    debugImplementation(libs.androidx.ui.tooling)
}
