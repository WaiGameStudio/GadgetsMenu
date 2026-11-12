package local.gadgetsmenu;

import com.google.gson.GsonBuilder;
import java.io.PrintWriter;
import java.io.StringWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.util.*;
import java.util.zip.ZipFile;
import org.objectweb.asm.ClassReader;
import org.objectweb.asm.tree.*;
import org.objectweb.asm.util.Textifier;
import org.objectweb.asm.util.TraceClassVisitor;
import org.objectweb.asm.util.TraceMethodVisitor;

/** Static analysis only: no classes from the input JAR are loaded or executed. */
public final class Inventory {
    private static String hash(String text) throws Exception {
        return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(text.getBytes(StandardCharsets.UTF_8)));
    }
    private static String render(MethodNode method) {
        Textifier printer = new Textifier();
        method.accept(new TraceMethodVisitor(printer));
        StringWriter writer = new StringWriter();
        printer.print(new PrintWriter(writer));
        return writer.toString().replace("\r\n", "\n");
    }
    public static void main(String[] args) throws Exception {
        Map<String, Object> classes = new TreeMap<>();
        try (ZipFile zip = new ZipFile(args[0])) {
            for (var entry : Collections.list(zip.entries())) {
                if (!entry.getName().endsWith(".class")) continue;
                ClassNode node = new ClassNode();
                new ClassReader(zip.getInputStream(entry).readAllBytes()).accept(node, ClassReader.SKIP_DEBUG | ClassReader.SKIP_FRAMES);
                Map<String, Object> methods = new TreeMap<>();
                Set<String> references = new TreeSet<>();
                for (MethodNode method : node.methods) {
                    methods.put(method.name + method.desc, hash(render(method)));
                    for (var instruction : method.instructions) {
                        if (instruction instanceof MethodInsnNode m) references.add(m.owner + ".class");
                        if (instruction instanceof FieldInsnNode f) references.add(f.owner + ".class");
                        if (instruction instanceof TypeInsnNode t) references.add(t.desc + ".class");
                    }
                }
                StringWriter text = new StringWriter();
                node.accept(new TraceClassVisitor(new PrintWriter(text)));
                classes.put(entry.getName(), Map.of("major", node.version, "methods", methods,
                        "references", references, "normalizedHash", hash(text.toString().replace("\r\n", "\n"))));
            }
        }
        Path output = Path.of(args[1]);
        Files.createDirectories(output.toAbsolutePath().getParent());
        Files.writeString(output, new GsonBuilder().setPrettyPrinting().create().toJson(classes) + "\n", StandardCharsets.UTF_8);
        System.out.println("Inventoried " + classes.size() + " classes without executing target code.");
    }
}
