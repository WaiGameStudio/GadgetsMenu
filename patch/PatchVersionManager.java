import java.nio.file.Files;
import java.nio.file.Paths;
import java.util.Arrays;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.zip.ZipFile;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.ClassVisitor;
import org.objectweb.asm.ClassWriter;
import org.objectweb.asm.Opcodes;
import org.objectweb.asm.MethodVisitor;
import org.objectweb.asm.tree.ClassNode;
import org.objectweb.asm.tree.MethodNode;
import org.objectweb.asm.util.Textifier;
import org.objectweb.asm.util.TraceMethodVisitor;
import java.io.PrintWriter;
import java.io.StringWriter;

public final class PatchVersionManager {
    private static final String ENTRY = "com/yapzhenyie/GadgetsMenu/utils/VersionManager.class";
    private static final Set<String> TARGETS = new HashSet<>(Arrays.asList(
            "getMinecraftVersion()Ljava/lang/String;",
            "isSupported(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;I)Z"));

    private static ClassNode node(byte[] bytes) {
        ClassNode node = new ClassNode();
        new ClassReader(bytes).accept(node, 0);
        return node;
    }

    private static String trace(MethodNode method) {
        Textifier printer = new Textifier();
        method.accept(new TraceMethodVisitor(printer));
        StringWriter text = new StringWriter();
        printer.print(new PrintWriter(text));
        return text.toString();
    }

    public static void main(String[] args) throws Exception {
        byte[] original;
        try (ZipFile zip = new ZipFile(args[0])) {
            original = zip.getInputStream(zip.getEntry(ENTRY)).readAllBytes();
        }
        ClassNode donor = node(Files.readAllBytes(Paths.get(args[1])));
        Map<String, MethodNode> replacements = new HashMap<>();
        for (MethodNode method : donor.methods) {
            String key = method.name + method.desc;
            if (TARGETS.contains(key)) replacements.put(key, method);
        }
        if (!replacements.keySet().equals(TARGETS)) throw new AssertionError("Missing donor methods");
        ClassReader reader = new ClassReader(original);
        ClassWriter writer = new ClassWriter(reader, 0);
        Set<String> changed = new HashSet<>();
        reader.accept(new ClassVisitor(Opcodes.ASM9, writer) {
            @Override public MethodVisitor visitMethod(int access, String name, String descriptor,
                    String signature, String[] exceptions) {
                String key = name + descriptor;
                MethodNode replacement = replacements.get(key);
                if (replacement == null) return super.visitMethod(access, name, descriptor, signature, exceptions);
                if (replacement.access != access || !changed.add(key)) throw new AssertionError(key);
                replacement.accept(writer);
                return null;
            }
        }, 0);
        if (!changed.equals(TARGETS)) throw new AssertionError("Unexpected patch scope");
        byte[] result = writer.toByteArray();
        ClassNode before = node(original);
        ClassNode after = node(result);
        if (before.version != after.version || before.fields.size() != after.fields.size()
                || before.methods.size() != after.methods.size()) throw new AssertionError("Class shape changed");
        int unchanged = 0;
        for (int i = 0; i < before.methods.size(); i++) {
            MethodNode a = before.methods.get(i);
            MethodNode b = after.methods.get(i);
            if (!a.name.equals(b.name) || !a.desc.equals(b.desc)) throw new AssertionError("Method shape changed");
            if (!TARGETS.contains(a.name + a.desc)) {
                if (!trace(a).equals(trace(b))) throw new AssertionError("Unrelated method changed: " + a.name);
                unchanged++;
            }
        }
        Files.createDirectories(Paths.get(args[2]).getParent());
        Files.write(Paths.get(args[2]), result);
        System.out.println("Patched exactly 2 methods; " + unchanged + " unrelated methods unchanged; class major=" + after.version);
    }
}
