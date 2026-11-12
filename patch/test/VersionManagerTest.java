import com.yapzhenyie.GadgetsMenu.utils.ServerVersion;
import com.yapzhenyie.GadgetsMenu.utils.VersionManager;
import java.lang.reflect.Field;
import java.util.Map;
import java.util.Objects;
import java.util.logging.Handler;
import java.util.logging.LogRecord;
import java.util.logging.Logger;
import org.bukkit.Bukkit;

public final class VersionManagerTest {
    private static int checks;
    private static String warning;

    private static void check(boolean condition, String label) {
        if (!condition) throw new AssertionError(label);
        checks++;
        System.out.println("PASS " + label);
    }

    private static void equal(Object expected, Object actual, String label) {
        check(Objects.equals(expected, actual), label + " [expected=" + expected + ", actual=" + actual + "]");
    }

    private static void reset(String api, String display) throws Exception {
        Field version = VersionManager.class.getDeclaredField("MINECRAFT_VERSION");
        version.setAccessible(true);
        version.set(null, null);
        Field cache = VersionManager.class.getDeclaredField("SERVER_VERSION_GREATER_EQUAL_LIST");
        cache.setAccessible(true);
        ((Map<?, ?>) cache.get(null)).clear();
        ServerVersion.setCurrentServerVersion(null);
        Bukkit.apiVersion = api;
        Bukkit.serverVersion = display;
        Bukkit.apiReads = 0;
        Bukkit.displayReads = 0;
        Bukkit.server = new org.bukkit.craftbukkit.v1_21_R7.CraftServer();
        warning = null;
    }

    private static void original() throws Exception {
        reset("1.21.11-R0.1-SNAPSHOT", "Custom CraftBukkit 1.21.11");
        equal(null, VersionManager.getMinecraftVersion(), "original parser fails without MC marker");
        try {
            VersionManager.isSupported(VersionManager.getMinecraftVersion(), "1.8", "26.3", 2);
            throw new AssertionError("Original did not reproduce NPE");
        } catch (NullPointerException expected) {
            check(expected.getMessage().contains("reference"), "reproduced reference-null exception");
            expected.printStackTrace(System.out);
        }
        reset("1.21.11-R0.1-SNAPSHOT", "git-Bukkit-test (MC: 1.21.11)");
        equal("1.21.11", VersionManager.getMinecraftVersion(), "original legacy format baseline");
    }

    private static void patched() throws Exception {
        reset("1.21.11-R0.1-SNAPSHOT", "Custom CraftBukkit 1.21.11");
        equal("1.21.11", VersionManager.getMinecraftVersion(), "API version without MC marker");
        check(VersionManager.isSupported(VersionManager.getMinecraftVersion(), "1.8", "26.3", 2),
                "onEnable version-range gate accepts 1.21.11");
        new VersionManager();
        equal(ServerVersion.v1_21_R7, ServerVersion.getCurrentServerVersion(), "versioned CraftBukkit selects R7");
        check(!VersionManager.isSupportDropped(ServerVersion.getCurrentServerVersion()), "R7 support not dropped");
        equal("v1_21_R7", VersionManager.getBukkitVersion(), "existing package detection unchanged");
        check(VersionManager.isServerVersionGreaterEqual("1.21.10"), "server comparison true branch");
        check(!VersionManager.isServerVersionGreaterEqual("1.21.12"), "server comparison false branch");
        check(VersionManager.isServerVersionGreaterEqual("1.21.10"), "server comparison cache");
        check(VersionManager.isServerVersionBetween("1.21.10", "1.21.12"), "server range unchanged");
        check(VersionManager.isServerVersionEqual(ServerVersion.v1_21_R7), "server enum comparison unchanged");
        int apiReads = Bukkit.apiReads;
        int displayReads = Bukkit.displayReads;
        Bukkit.apiVersion = "invalid";
        equal("1.21.11", VersionManager.getMinecraftVersion(), "successful result cached");
        equal(apiReads, Bukkit.apiReads, "cache avoids new API reads");
        equal(displayReads, Bukkit.displayReads, "cache avoids display reads");

        reset("1.21.11-R0.1-SNAPSHOT", "Custom server");
        Bukkit.server = new org.bukkit.craftbukkit.CraftServer();
        new VersionManager();
        equal(ServerVersion.v1_21_R7, ServerVersion.getCurrentServerVersion(), "unversioned package selects R7 from release");

        for (String api : new String[]{"1.21.11", "1.21.11-R0.1-SNAPSHOT", " 1.21.11-R0.1-SNAPSHOT "}) {
            reset(api, "unused");
            equal("1.21.11", VersionManager.getMinecraftVersion(), "Bukkit format " + api);
        }
        reset("1.21.11-R0.1-SNAPSHOT", "git-Bukkit-test (MC: 1.20.6)");
        equal("1.21.11", VersionManager.getMinecraftVersion(), "API takes priority over display string");

        for (String api : new String[]{null, "", "unknown", "v1_21_R7"}) {
            reset(api, "git-Bukkit-test (MC: 1.21.11)");
            equal("1.21.11", VersionManager.getMinecraftVersion(), "legacy fallback for " + api);
        }
        reset(null, "Custom (MC:   1.21.11 )");
        equal("1.21.11", VersionManager.getMinecraftVersion(), "fallback whitespace");

        for (String invalid : new String[]{null, "", "unknown", "1", "1..21.11", "1.21.11.",
                "1.21.11.1", "x1.21.11", "1.21.11junk", "git-Custom-1.21.11"}) {
            reset(invalid, invalid);
            equal(null, VersionManager.getMinecraftVersion(), "unknown format not guessed: " + invalid);
            check(!VersionManager.isSupported(VersionManager.getMinecraftVersion(), "1.8", "26.3", 2),
                    "unknown version safely rejected: " + invalid);
            check(warning != null && warning.contains("Cannot determine Minecraft version")
                    && warning.contains("Bukkit.getBukkitVersion()") && warning.contains("Bukkit.getVersion()"),
                    "unknown version diagnostic: " + invalid);
        }
        reset(null, null);
        equal(null, VersionManager.getMinecraftVersion(), "failed parse remains uncached");
        Bukkit.apiVersion = "1.21.11-R0.1-SNAPSHOT";
        equal("1.21.11", VersionManager.getMinecraftVersion(), "retry after failed parse");

        for (ServerVersion version : ServerVersion.values()) {
            for (String release : version.getSpigotReleases()) {
                reset(release + "-R0.1-SNAPSHOT", "no MC marker");
                equal(release, VersionManager.getMinecraftVersion(), "existing mapped release " + release);
                equal(version, ServerVersion.valueOfSpigotRelease(VersionManager.getMinecraftVersion()),
                        "existing enum mapping " + release);
            }
        }
        check(VersionManager.isSupported("1.8", "1.8", "26.3", 2), "lower bound inclusive");
        check(VersionManager.isSupported("26.3", "1.8", "26.3", 2), "upper bound inclusive");
        check(!VersionManager.isSupported("1.7.10", "1.8", "26.3", 2), "below lower bound rejected");
        check(!VersionManager.isSupported("26.4", "1.8", "26.3", 2), "above upper bound rejected");
        check(!VersionManager.isSupported(null, "1.8", "26.3", 2), "null range gate rejected");
        check(VersionManager.isVersionGreater("1.21.11", "1.21.9"), "numeric not lexical comparison");
        check(VersionManager.isVersionGreaterEqual("1.21", "1.21.0"), "comparison zero padding");
        check(VersionManager.isVersionLess("1.20.6", "1.21"), "less comparison unchanged");
        check(VersionManager.isVersionLessEqual("1.21.11", "1.21.11"), "equal comparison unchanged");
    }

    public static void main(String[] args) throws Exception {
        Logger logger = Bukkit.getLogger();
        logger.setUseParentHandlers(false);
        logger.addHandler(new Handler() {
            public void publish(LogRecord record) { warning = record.getMessage(); }
            public void flush() {}
            public void close() {}
        });
        if ("original".equals(args[0])) original(); else patched();
        System.out.println("ALL PASS: " + checks + " assertions (" + args[0] + ")");
    }
}
