package org.bukkit;

import java.util.logging.Logger;

// Isolated test double, never packaged in the plugin.
public final class Bukkit {
    public static String apiVersion;
    public static String serverVersion;
    public static Server server = new org.bukkit.craftbukkit.v1_21_R7.CraftServer();
    public static int apiReads;
    public static int displayReads;
    public static String getBukkitVersion() { apiReads++; return apiVersion; }
    public static String getVersion() { displayReads++; return serverVersion; }
    public static String getName() { return "CraftBukkit"; }
    public static Server getServer() { return server; }
    public static Logger getLogger() { return Logger.getLogger("VersionManagerTest"); }
}
