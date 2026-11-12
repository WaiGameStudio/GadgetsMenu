package com.yapzhenyie.GadgetsMenu.utils;

import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.bukkit.Bukkit;

// Method donor only. The build transplants exactly two methods into the original class.
public class VersionManager {
    private static String MINECRAFT_VERSION;

    public static String getMinecraftVersion() {
        if (MINECRAFT_VERSION != null) {
            return MINECRAFT_VERSION;
        }
        String bukkitVersion = Bukkit.getBukkitVersion();
        if (bukkitVersion != null) {
            Matcher matcher = Pattern.compile(
                    "^([0-9]+\\.[0-9]+(?:\\.[0-9]+)?)(?:-[A-Za-z0-9._-]+)?$")
                    .matcher(bukkitVersion.trim());
            if (matcher.matches()) {
                MINECRAFT_VERSION = matcher.group(1);
                return MINECRAFT_VERSION;
            }
        }
        String serverVersion = Bukkit.getVersion();
        if (serverVersion != null) {
            Matcher matcher = Pattern.compile(
                    "\\(MC: *([0-9]+\\.[0-9]+(?:\\.[0-9]+)?) *\\)")
                    .matcher(serverVersion);
            if (matcher.find()) {
                MINECRAFT_VERSION = matcher.group(1);
            }
        }
        if (MINECRAFT_VERSION == null) {
            Bukkit.getLogger().warning(
                    "[GadgetsMenu] Cannot determine Minecraft version: Bukkit.getBukkitVersion()='"
                    + bukkitVersion + "', Bukkit.getVersion()='" + serverVersion + "'.");
        }
        return MINECRAFT_VERSION;
    }

    public static boolean isSupported(String reference, String lowest, String highest, int splitLimit) {
        return reference != null
                && compare(reference, lowest, splitLimit) >= 0
                && compare(reference, highest, splitLimit) <= 0;
    }

    // Compilation placeholder: the original implementation is retained in the output JAR.
    private static int compare(String reference, String comparison, int splitLimit) {
        throw new AssertionError("Do not package the donor class");
    }
}
