---
name: game-code-review
description: >
  用于游戏项目的策划／需求一致性核对、功能验收、代码审查、改动回归和问题诊断，
  包括整体回归 check、广告与 SDK、跨平台崩溃／闪退／卡死、正反逻辑、边界与异常操作、状态机、活动、玩法与道具、新老功能耦合、埋点上报及多语言／漏译／缺字检查。
  也用于项目问题台账、忽略／暂缓与修复复核，以及 /game-code-review、stop-review 的会话模式控制或查询。
metadata:
  short-description: 审查游戏需求与逻辑，优先排查崩溃和广告风险，维护项目外地图与问题台账
---

# Game Code Review

默认用中文向策划、测试及非专业游戏程序员报告。沿实际执行链审查，结论与证据相符。业务源码默认只读，项目外地图和台账按规则维护；修复代码、导出测试用例按用户任务执行。

## 会话控制

新会话默认“自动”，按任务相关性选用，不因此持续开启。先处理用户模式指令；单独控制／查询模式、说明／编辑技能不启动项目审查，关闭时也可响应。

| 用户指令 | 会话模式与后续行为 |
|---|---|
| `/game-code-review` | 开启：本对话后续游戏审查、需求核对、诊断及修复复核持续使用，直到关闭或恢复自动。 |
| `stop-review` | 关闭：停止自动使用技能；普通审查请求仍正常处理，模式保持关闭。 |
| 明确要求“恢复 game-code-review 的自动调用” | 自动：恢复按任务相关性选用。 |

- **识别指令：** 命令可单独输入或附带任务，以用户最新执行意图为准；重复指令不改变结果。查询、引用、解释命令或读取技能中的默认提示不切换模式。
- **单次调用：** 明确技能调用按用户指定范围执行；未要求持续开启时仅用于当前任务，结束后保留原模式，包括原先的关闭。
- **持续范围：** 开启后相关追问沿用审查方法，无关话题正常回答且保留模式；切换项目重新识别架构与需求。简单解释直接回答，新增问题遵循报告规范；审查范围和修改权限由用户任务决定。
- **反馈与续接：** 模式指令简短确认，附带任务继续执行，不每轮重复声明。同一会话的交接摘要保留模式、技能路径、审查对象、台账路径和待查事项；新会话的项目处理决定从台账读取。

模式依赖宿主传入上下文，不写全局开关或宣称注册了宿主命令、具备程序级状态保证。与简略回复技能并用时，仍保留需求依据、复现前提、验证状态和代码证据。

<a id="code-map-assist"></a>
## 代码地图辅助

实际审查可访问且可归属的项目时，按[地图联动规则](references/code-map-assist.md)调用 `project-code-map`：首次建立当前目标所需导航，相关结构／关键链路变化或导航失效时增量更新，与源码一致则复用，无需另行请求维护授权。辅助完成后继续原审查。

默认入口：`~/.local/share/project-code-maps/<项目名>-<路径哈希>/INDEX.md`。技能关闭时不触发地图写入；范围、版本核实与失败回退见联动规则。

<a id="issue-tracking"></a>
## 项目问题台账

实际项目审查、诊断或修复复核时，按[台账规则](references/issue-tracking.md)读取历史并简述待办；首次审查用[模板](assets/issues-template.md)建立项目外 `review/issues.md`。正式问题自动入表、去重并保留用户决定；需求待确认不入表、不分配编号。已忽略且条件未变的条目不重复展开；确认解决后移出当前表并留历史。

用户单独维护台账时只处理指定记录，不启动审查。两项辅助均不因模式查询、技能说明／编辑、无关话题或无法归属的片段而写文件。禁止任何写入时只读；仅要求不改项目文件时仍可维护外部记录。读取／维护失败时说明限制并继续审查，具体按对应规则处理。

## 快速定位

按下表读取相关章节，可命中多行；R/S/A/F/C/V 是稳定标识。已加载且仍可用的章节不重读，细节缺失或问题类型变化时补读。

**控制开销：** 简单问题查相关约束与直接依赖；复杂功能沿真实关系扩展，导航不限制影响范围。已有记录经当前需求与代码核实后复用，只补变化和缺口。报告仅展示影响结论的关系，不强制另建过程表或图。

多行命中先查最具体的现象：拒绝后仍扣资源先 R2，到账次数／金额错误先 A2；无法继续先 S3，涉及 UI 开关／复用再补 F2。模糊描述不能作为预设机制的依据。

| 用户问题或代码信号 | 首读章节 | 涉及时补充 |
|---|---|---|
| 每次实际项目审查；已知问题、忽略／暂缓、修复复核、旧问题复发 | [项目问题台账](#issue-tracking) | 审查前读历史，报告前更新；专项检查仍按下列问题类型选择 |
| 整体回归 check、版本全面检查 | [C1 稳定性初筛](references/stability-sdk-review-checklist.md#c1-triage) | 在声明范围内先检查启动、SDK 回调与全局阻塞，再按实际模块选专项；不止看 diff |
| 广告检查、广告初始化／加载／展示／返回异常 | [C3 广告完整链路](references/stability-sdk-review-checklist.md#c3-ads) | [C2 跨语言与平台边界](references/stability-sdk-review-checklist.md#c2-native)、S3 恢复、A2 奖励 |
| 崩溃、闪退、ANR、启动失败、全局无响应；原生回调新增 Post／异步派发／跨帧保存 | [C1 稳定性初筛](references/stability-sdk-review-checklist.md#c1-triage) | [C2 所有权与线程](references/stability-sdk-review-checklist.md#c2-native)、[C4 验证](references/stability-sdk-review-checklist.md#c4-validation)；有原生边界时不可止步于托管封装 |
| 首次审查无地图、已有地图失效、项目结构或关键链路变化 | [代码地图辅助](#code-map-assist) | 调用 `project-code-map` 建立或增量更新后继续本次审查 |
| 对照策划文档、跨步骤约束、漏做／多做、实现与需求不一致 | [R1 需求拆解与依据](references/requirements-review-checklist.md#r1-requirements) | [R3 规则依赖与双向追踪](references/requirements-review-checklist.md#r3-traceability) |
| 正反逻辑、门槛边界、拒绝、取消、失败后仍有副作用 | [R2 条件与正反路径](references/requirements-review-checklist.md#r2-conditions) | 影响资源时读 [A2 资源与奖励](references/activity-reward-review-checklist.md#a2-rewards) |
| 胜负、复活、暂停、输入锁、计时器、状态不对 | [S1 组合状态](references/state-machine-review-checklist.md#s1-states) | 延迟或竞争时读 [S2 事件时序](references/state-machine-review-checklist.md#s2-ordering) |
| 卡住、一直等待、无法继续、退出后未恢复 | [S3 阻塞与恢复](references/state-machine-review-checklist.md#s3-recovery) | UI 开关与复用读 [F2 界面生命周期](references/framework-data-review-checklist.md#f2-ui) |
| 道具／增益叠加、覆盖、到期撤销、玩法互相干扰 | [S4 效果与玩法耦合](references/state-machine-review-checklist.md#s4-effects) | 跨模块传播读 [F1 依赖与事件](references/framework-data-review-checklist.md#f1-dependencies) |
| 活动开放、结束、报名、领奖、冷却、下一轮 | [A1 活动生命周期](references/activity-reward-review-checklist.md#a1-activity) | 奖励到账读 [A2 资源与奖励](references/activity-reward-review-checklist.md#a2-rewards) |
| 错扣／重扣、漏奖／重奖、购买／广告回调、中断领取 | [A2 资源与奖励](references/activity-reward-review-checklist.md#a2-rewards) | 写盘与恢复读 [F3 存储边界](references/framework-data-review-checklist.md#f3-storage) |
| 重启丢数据、旧存档、升级、登录或换账号后错乱 | [F3 存储边界](references/framework-data-review-checklist.md#f3-storage) | 跨活动轮次读 [A1 活动生命周期](references/activity-reward-review-checklist.md#a1-activity) |
| SDK 移除或升级、混淆／保留规则调整（如 R8／ProGuard）、支付或启动流程变化 | [F3 升级兼容](references/framework-data-review-checklist.md#f3-storage) | 必须评估老包覆盖升级；初始化依赖读 [F1](references/framework-data-review-checklist.md#f1-dependencies)，订单恢复读 [A2](references/activity-reward-review-checklist.md#a2-rewards) |
| UI 不刷新、弹窗遮挡、跨界面跳转／返回异常、重复通知、空引用、Prefab／场景绑定 | [F2 界面生命周期](references/framework-data-review-checklist.md#f2-ui) | 异步回调读 [S2 事件时序](references/state-machine-review-checklist.md#s2-ordering) |
| 配置、读表、资源缺失、数据来源或版本不一致 | [F4 配置与资源](references/framework-data-review-checklist.md#f4-config) | 只追踪当前项目实际来源与消费链 |
| 多语言、本地化、漏译、缺字、翻译语义、语言切换、翻译表／字体资源、占位符或多语言 Key 引用 | [L1 多语言专项与内置工具](references/localization-review.md) | 按配置批量检查，逐行对照英文复核各语言语义，再核实候选实际消费路径；UI 刷新补 F2，导表与打包来源补 F4 |
| 埋点／打点、上报时机、字段错误、重复上报或漏报；相关业务路径包含上报 | [F5 埋点上报](references/framework-data-review-checklist.md#f5-telemetry) | 条件分支读 [R2](references/requirements-review-checklist.md#r2-conditions)，延迟发送读 [S2](references/state-machine-review-checklist.md#s2-ordering) |
| 新老功能耦合、公共基类／事件／调度改动、回归 | [F1 依赖与事件](references/framework-data-review-checklist.md#f1-dependencies) | 按受影响行为选择本表其他章节 |
| 判断是否查完、能否下结论、仍有证据缺口 | [V1 完成条件](references/evidence-validation.md#v1-completion) | 需求结论使用 R4；缺口不阻塞其他可独立检查的部分 |
| 复杂根因未明、反馈与代码冲突、发现可能推翻判断的保护机制 | [V2 替代原因与反证](references/evidence-validation.md#v2-alternatives) | 按涉及的模块补查专项；简单且证据完整的问题直接报告 |
| 设计／评估验证方法、已有测试通过、复核 Bug 是否解决 | [V3 验证有效性](references/evidence-validation.md#v3-validation) | SDK／真机验证补 C4；关闭记录仍按台账规则 |
| 怎样写问题、手动复现、区分实测与推断 | [问题报告](#finding-report) | 需求结论或上游阻塞读 [R4 核对结果](references/requirements-review-checklist.md#r4-results) |

## 核心审查流程

1. **确定依据和模式。** 文档核对覆盖相关完整实现；功能审查沿目标链路；改动回归沿变更及影响面；诊断从现象与触发条件回溯。Diff 仅辅助定位，没有 diff 仍可审查。指定提交时固定 revision，使用该快照的源码及行号，不混入后续实现。
2. **识别项目。** 阅读项目指导、[台账](#issue-tracking)及[地图](#code-map-assist)，定位真实入口、状态归属、事件机制、生命周期和数据来源。地图、历史及相似项目只提供线索，须由当前源码核实；不预设表结构、AB 读表方式或业务调用链。
3. **选专项并追踪。** 按导航选择清单，还原触发、校验、状态／资源变化、异步、展示／结算、存储和清理的实际顺序，不将这些维度当作固定执行顺序。查明相关读写方、事件发送／接收方及间接影响。
4. **核对正反与恢复。** 检查允许、禁止、例外、边界、重复、中断及失败恢复，追踪不应发生的副作用。旧路径可对比，不能单独证明正确。
5. **验证并控制范围。** 优先排查崩溃、启动失败、全局阻塞，再查局部阻塞、进度／资源损失和重复结算。高影响且证据未闭合的路径优先补证，不因缺日志或非必现降到普通 UI 问题之后。按实际共享状态、事件与执行顺序选择组合，避免穷举；记录未闭合链路，可行时做聚焦测试或确定性推演。
6. **核实结论并维护台账。** 所有专项在确认问题前，按 [V1 问题成立前检查](references/evidence-validation.md#v1-reachability)核实触发来源、适用条件、有效配置和最终影响，再核对其余完成条件；复杂根因未闭合时补 V2，使用验证结果时补 V3。标明缺口并继续独立可查部分，按[台账规则](references/issue-tracking.md)记录、去重或结束问题；局部通过不代表整个功能正常。

<a id="finding-report"></a>
## 问题报告

开头按[提醒规则](references/issue-tracking.md#reminders)简述待办，未复核记录注明历史状态。正文重点展示新增问题、重要变化和本次复核结果，关联台账编号；无新增问题不代表已知问题全部解决。

**默认简洁报告：** 用一段总结检查／验证状态、明确问题数量及影响结论的未覆盖项，随后只列明确问题。每项保留严重程度、触发条件与实际影响、验证状态、关键证据链接；修复复核注明已修复／未修复。候选和待验证项在摘要中计数并链接证据，不混入明确问题。具体高风险会影响发布判断时单独提示。用户要求详细报告或复现步骤时，再展开下述完整格式；完整证据保留在扫描结果或台账中，不在报告、台账、地图重复长篇描述。

整体回归、广告或稳定性审查先给稳定性结论：已确认的高影响问题、具体高风险及缺失证据；其他专项不添加无关结论。确定缺陷与待验证风险分开，各按影响排序，同根因连锁表现合并。崩溃风险即使根因待验证，也优先于普通 UI 问题。严重程度与证据状态独立：

| 严重程度 | 判定依据 |
|---|---|
| 致命／P0 | 已确认普通启动或核心路径在受影响平台／版本大范围不可用，或高概率反复崩溃且无可用绕过；建议阻断发布。静态猜测不定 P0，单台反馈不推为全平台发生率 |
| 高／P1 | 可达路径造成崩溃／闪退、ANR、需重启的全局输入锁或无法恢复的核心阻塞；进度／资产严重损失。偶现不自动降级 |
| 中／P2、低／P3 | 按局部功能损失、可恢复性和范围判断；可退出的局部动画停止通常为中，轻微展示问题通常为低，不统称死锁 |

根因未闭合，但有可达入口、危险操作和具体缺失保障时，可报“潜在高／P1，仍需验证”，说明前提、缺失证据及最小验证动作，不计入确定缺陷；一般猜测只写覆盖限制。用户／测试已复现的闪退保留现象影响等级，另标根因状态；缺日志不降级，未知的平台范围不外推。

需要展开的详细问题按以下顺序输出：

1. **标题与严重程度**：以玩家现象命名，不以类名、变量名或异常名作主要描述。
2. **问题描述**：触发情况、可见现象及后果，用玩家能理解的语言解释必要术语。
3. **预期与实际**：引用需求或明确规则；未执行的结果写“根据代码推导……”。依据不清时列为当次需求待明确，不自行补规则或写入台账。
4. **复现前提与手动步骤**：前提使用玩家可识别的账号／版本／关卡／活动状态，步骤用编号列表，写明动作及异常结果。入口、按钮文案与条件须有依据；无真实文案时描述功能动作。内部组号、变量和函数调用放在末尾技术证据中，玩家无法构造的前提注明需技术协助。
5. **验证状态**：使用下表标记并限定范围；时序问题说明触发窗口，不承诺未经验证的必现率。
6. **原因与代码证据**：末尾用一句通俗话解释原因，附精确文件链接和行号，必要时给最小修正方向。源码／配置及技术细节集中在此；需求引用可随预期给出。

**纯埋点问题：** 同样按上述顺序，用统计异常命名，说明错误记录及其对统计判断的影响，据此定级。玩家动作仅作触发步骤，另列日志、抓包或平台数据等观察手段与工具协助；不虚构界面异常，区分待发送数据错误与实际平台统计失真。

| 验证状态 | 使用条件 |
|---|---|
| 已实际复现 | 亲自执行并观察异常，说明环境、动作和结果；函数／单元模拟不等于玩家流程实测 |
| 用户／测试已复现 | 标注来源、平台／版本、动作与已知频率，缺项写未知；只确认反馈现象，不冒充助手实测或自动确认根因 |
| 代码链路明确，尚未实测 | 已通过 [问题成立前检查](references/evidence-validation.md#v1-reachability)，前提、状态变化和影响有完整静态证据；可作为明确问题，不能声称运行验证 |
| 仍需验证 | 可达性、顺序、外部行为或关键状态证据不足；放在待验证部分，不计入确定缺陷 |

自动化验证补充命令／方式、结果及覆盖边界。复现步骤按以下依据给出：

- 玩家可达但未实测：标注“根据代码推导的复现步骤，尚未实测”。
- 需注入异常、特殊数据或内部回调：标注“需要测试工具／技术协助验证”，写明状态、事件和观察结果，不编造纯手动步骤。
- 可达性不明：说明缺失证据和核实方向，不给伪确定步骤。

需求核对仍按 [R4 核对结果](references/requirements-review-checklist.md#r4-results)说明歧义和核对状态；无文档则按现有依据说明。范围及关键未覆盖项并入摘要，详细清单链接证据。稳定性审查说明已覆盖平台与链路；未发现确定缺陷也要说明检查内容、依据和未验证部分，不等于版本稳定性通过。

手动复现保留在问题条目内；用户另行要求生成、整理或导出测试用例时使用 `test-case-five-columns`，不把普通问题报告改成用例表。
