# Chaquopy loads Python by reflection; keep the bridge and Python runtime.
-keep class com.chaquo.python.** { *; }
-keepclassmembers class ai.atif.assistant.MainActivity$VoiceBridge {
    public *;
}
