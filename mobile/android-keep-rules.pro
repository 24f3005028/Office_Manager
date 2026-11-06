# WorkManager 2.9.x instantiates these classes through reflection. AGP 9/R8
# full mode can otherwise retain the class but remove its no-arg constructor,
# crashing AndroidX Startup before React Native starts.
# https://github.com/expo/expo/issues/51337
-keep class * extends androidx.room.RoomDatabase { <init>(); }
-keep class * extends androidx.work.InputMerger { <init>(); }
