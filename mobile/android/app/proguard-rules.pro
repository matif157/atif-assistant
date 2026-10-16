# Chaquopy loads Python by reflection and talks to it over JNI; R8 must not
# strip any of the bridge or the runtime it reflects into.
-keep class com.chaquo.python.** { *; }
-keep class com.chaquo.python.Python { *; }
-keep class com.chaquo.python.android.AndroidPlatform { *; }
-keep class ai.atif.assistant.MainActivity { *; }
-keepclassmembers class ai.atif.assistant.MainActivity$VoiceBridge {
    public *;
}

# The web UI calls these from JavaScript; annotation-based keeping is not
# applied to library-shipped classes, so state it outright.
-keepclassmembers class * {
    @android.webkit.JavascriptInterface <methods>;
}

-dontwarn com.chaquo.python.**
-dontwarn java.nio.**
