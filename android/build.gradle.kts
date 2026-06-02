plugins {
    id("com.android.application") version "8.3.0" apply false
    kotlin("android") version "1.10.0" apply false
}

allprojects {
    repositories {
        google()
        mavenCentral()
    }
}
