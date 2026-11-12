# GadgetsMenu 非官方补丁与本地扩展工具

本仓库不是 GadgetsMenu 官方源码、开源复刻或完整插件发行版。这里只发布自行编写的修复方法、字节码移植工具、维护脚本、测试与说明。使用者必须自行合法取得原插件，并遵守其许可及适用法律。

## 公开范围与许可证

自写内容采用 [MIT 许可证](LICENSE)。MIT **不包括** GadgetsMenu 原版、反编译代码、原配置/资源、第三方依赖，以及包含这些内容的合成插件 JAR；不代表获得了它们的再分发授权。项目名称和相关权利仍属于其权利人，本项目与官方无隶属关系。

公开文件精确列于根目录 `public-files.json`。以下仅保存在使用者本机，禁止提交或上传为 Release/附件：

- `GadgetsMenu.jar`、`upstream/`：自备原包、私有快照、反编译源码与资源、指纹清单。
- `src/`：旧工程留下的完整反编译覆盖源码，只供本地参考，默认不参与编译。
- `libs/`：自行取得的编译依赖。
- `build/`、`tooling/build/`：缓存、中间字节码、完整插件产物。
- `workspace.json`、`overlay-lock.json`、IDEA 配置及本地日志。
- `docs/` 中除本 README、LICENSE 外的生成报告；升级 diff 可能包含上游代码。

仓库不附带 Gradle wrapper、Recaf、Bukkit API 或任何第三方 JAR。它们各自适用原许可证。

## 已实现的修复及边界

针对 Bukkit 1.21.11 环境中版本解析得到 `null` 后，在 `VersionManager.compare` 中调用 `split` 引发的空指针：

1. 优先从 `Bukkit.getBukkitVersion()` 提取数字版本。
2. 无法解析时回退到 `Bukkit.getVersion()` 的 `(MC: ...)` 格式。
3. 仍未知时记录警告并返回“不支持”，不绕过版本检查。

默认只移植 `getMinecraftVersion()` 和四参数 `isSupported(...)` 两个自写方法。供体 `patch/src/.../VersionManager.java` **不是原类的完整源码**；其中 `compare` 是故意抛错的编译占位符，不能直接打包。ASM 工具保留上游其余方法，校验另外 19 个方法未变、类版本和成员数量不变。

当前锁定的输入基线：

- 插件版本：**5.35.0**（不能据此把日志中的 5.34.5 当作同一个包）。
- 原包 SHA-256：`18f366bbe8c9226d1646d79866eb011bd13cfbca01d74c3781edbc1a73ad651d`。
- 不符合哈希的包拒绝自动应用补丁；不要为了绕过检查随意修改基线。

版本逻辑使用 Bukkit 测试替身隔离验证，不等于真实服务器完整启动或所有 NMS 功能兼容。**当前没有新增凋零宠物**；把 YAML 的显示名改成“凋零”不会注册新实体类型或菜单功能。

## 本地准备与构建

需要 JDK 21、Python 3.10+、Gradle 9.3.0，以及包含 ASM、Gson、CFR 的本地 Recaf JAR。`java`、`javac`、`python`、`gradle` 需要可从命令行执行。Recaf 默认位置为 Windows `%APPDATA%/Recaf/recaf.jar`；其他位置每次传 `-PrecafJar=...`。工具不会自动下载原插件。

在克隆目录打开终端，以下是 PowerShell 示例（替换为自己的合法文件路径）：

```powershell
gradle help
gradle prepareUpstream "-PnewJar=C:/private/GadgetsMenu.jar" "-PrecafJar=C:/tools/recaf.jar"
# 必须单独执行下一条，让 Gradle 重新读取生成的本地基线配置。
gradle clean build originalRegression "-PrecafJar=C:/tools/recaf.jar"
```

首次准备自动生成私有快照和锁文件，不需要反编译源码或 Spigot API 即可构建现有版本补丁。已存在的基线、锁文件不会被准备命令覆盖。缺少原包时 `help` 可以运行，构建则明确拒绝继续。可选执行 `gradle wrapper` 在本机生成 wrapper，但生成文件不纳入公开清单。

输出为 `build/libs/GadgetsMenu-5.35.0-local.jar`。它是**合成的完整插件**，只在原版许可允许的范围内本地使用，不能因本仓库 MIT 就公开分发。不要部署供体 class、测试替身或 tooling JAR。部署前备份服务端插件与配置，停服后替换旧插件，避免同时加载两份 GadgetsMenu；本项目的隔离测试不能代替目标服务端启动验收。

### 验证命令与证据

```powershell
gradle build originalRegression "-PrecafJar=C:/tools/recaf.jar"
python tools/public_audit.py                 # 检查 Git 暂存区实际内容
python tools/public_audit.py --history       # 检查所有本地 refs 可达提交
```

- `versionRegression`：修补后版本解析、兼容边界、缓存与空值行为断言，使用 `-Xverify:all`。
- `originalRegression`：复现原包的相关失败条件。
- `workspaceTests`：模拟上游更新、冲突拒绝、哈希篡改、路径安全、合包及自写新增类实际执行；另含公开清单防误传测试。
- `patchVersionManager`：输出精确移植方法数量及未变方法数量。
- `docs/verification/assembly.json`：列出合成包实际新增/移除/改变条目与哈希。没有扩展代码时应只改变 VersionManager 主类，保留全部原 inner class。
- `docs/verification/version-regression.txt`：隔离版本逻辑测试结果。报告留在本机。

`auditPublic` / `--files` 只检查白名单中的工作文件，不代表 Git 历史已安全；发布前必须检查暂存区和可达历史。扫描只是防误传措施，不能自动证明代码原创或法律授权。

## IDEA 与后续添加内容

使用 IDEA 打开根目录 `build.gradle`，选择 JDK 21 和本地 Gradle，完成准备后重新加载 Gradle 工程。建议运行 Gradle `build` 任务，别把 IDEA 的单类编译结果当作插件成品。旧 `src/` 保留但已退出默认构建。

- 原创新增类放 `extensions/src/main/java/`，原创资源放 `extensions/src/main/resources/`。必要的 API JAR 自备放 `libs/`，只用于编译，不打入最终包。
- 新增文件必须人工审查并逐一加入 `public-files.json` 才能提交；不能复制上游完整类或资源后声称 MIT。
- 原有类修复优先使用方法级供体及专用移植器，并补充对应行为测试；不要把供体整个类作为扩展覆盖。
- 对已有原包条目的替换必须登记依赖/影响范围，工具用 `overlay-lock.json` 拦截未登记覆盖。`track` 只是记录哈希，不是兼容性或授权审查。
- 旧 `checkout` 命令生成的 `src/` 文件仅本地研究使用，不再自动编译。需要采用这种整类覆盖方式时，必须自行明确配置私有构建任务，不能混入公开默认构建。

仅添加 Java 类不会自动接入插件菜单/事件。新增宠物仍需实现实体行为、菜单类型注册、权限/配置及目标服务端测试；本仓库未承诺通用自定义宠物接口。

## 作者更新后的同步流程

```powershell
gradle importUpstream "-PnewJar=C:/private/new-GadgetsMenu.jar" "-PrecafJar=C:/tools/recaf.jar"
gradle compareUpstream "-Pcandidate=upstream/<导入命令输出的目录名>" "-PrecafJar=C:/tools/recaf.jar"
```

工具静态比较 JAR 条目、类和方法指纹，不执行待比较插件。报告写入私有 `docs/upgrades/`；受监控类发生变化或上游新增内容与本地扩展冲突时返回失败，不自动覆盖本地代码。

需要阅读源码时，先 `gradle :tooling:classes`，再使用 `python tools/workspace.py decompile upstream/<候选目录>`；Python 直接调用时可用环境变量 `RECAF_JAR` 指定工具。反编译结果仅供本地参考，不是作者原始源码，也不保证完整可编译。每个不同版本只需导入一次，旧快照不覆盖；可按差异集中审查受影响类，而不是手工重做整个工程。

当前方法补丁还由 `patch/baseline.json` 的完整原包哈希锁定。因此**即使差异报告无冲突，也不会自动把新包当作受支持基线**。升级必须人工确认调用接口、移植/移除已被官方修复的方法、更新原创补丁及受审查的基线规格/私有锁，再执行回归和真实服验证。`activate` 的通用无冲突流程不能代替补丁基线审查。工具能减少重复比较工作，不能保证自动无冲突合并或行为等价。

## 提交与防止再次泄漏

```powershell
git config core.hooksPath .githooks
# 审查新增原创文件、更新 public-files.json，再暂存需要公开的文件。
git add <经过审查的文件>
python tools/public_audit.py
git commit -m "Describe original patch changes"
python tools/public_audit.py --history
```

`.gitignore` 不能撤回已提交内容，白名单也不能阻止手工绕过检查。不要使用 `git push --mirror`、把旧备份分支推回远端、公开完整产物，或把私有升级报告加入清单。

本仓库从误包含私有内容的历史迁移为新的仅补丁根历史。旧克隆应先备份自己未提交的修改，再重新克隆；不要合并/推回旧历史。本地维护者保存的旧 Git bundle 只用于私有恢复。重写分支不能撤回他人下载、fork 或托管平台的缓存；需要进一步移除缓存时，应联系平台支持并遵循其政策。参阅 [GitHub 官方历史清理说明](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository)。
