/**
 * Presenter script: the 8-minute demo, section by section (for the human talking, not for the app).
 *
 * Budgets sum to 480 seconds. The panel shows elapsed / remaining and the current section; it never
 * drives the UI, so it cannot change a document or submit anything.
 */

export interface PresenterSection {
  id: string;
  title: string;
  /** Planned seconds for this section. */
  budget: number;
  cues: string[];
}

export const PRESENTER_SECTIONS: PresenterSection[] = [
  {
    id: 'opening',
    title: '开场：登录与工作台',
    budget: 40,
    cues: [
      '用 applicant 登录；指三栏：模块 / 文档 / AI 助手。',
      '右侧四个标签：Audit、Knowledge、Automation、Legal。',
      '底部 draft rev N：每次保存 bump；审计钉住版本，过期会标 stale。',
    ],
  },
  {
    id: 'audit',
    title: '★ 模板审计（核心）',
    budget: 180,
    cues: [
      '全选粘贴标准保函 → 等 Saved to server（draft rev 2）。',
      'Audit → standard → Run template audit（约 6 秒）。',
      '结论：5/6、100% 覆盖、1 条不符合（双方无地址/联系方式）。',
      '每条都引用原文，Show in document 可跳；没有引用不能算通过。',
      'Config details：口径 + 版本 + sha；Redaction steps：打码样例。',
      'Copy / Download .md / Print；强调总结是模型写的，pass ≠ 合规。',
    ],
  },
  {
    id: 'controls',
    title: '两个对照',
    budget: 40,
    cues: [
      '粘贴 333333 → Needs input：8 个必填缺失、6 项未评估。',
      '换 strict 配置 → 3/5，多出「管辖法律」「制裁声明」两条。',
      '一句话：口径可替换、可版本化，不是写死的判断。',
    ],
  },
  {
    id: 'approval',
    title: '提交 + 双人审批',
    budget: 90,
    cues: [
      'Submit new version → 确认链 → Pending first approval；编辑器只读。',
      'bankops：Approval → First approval → Approve → Pending second。',
      'compliance：Second approval → Approve → Approved。',
      'Activity 留痕；提交人不能审自己的单；批的是快照（rev + sha）。',
    ],
  },
  {
    id: 'legal',
    title: '法规风险扫描',
    budget: 80,
    cues: [
      'Open document… → sanctions-zh → Legal → Document check → Scan。',
      'Gate Blocked；Planned 12 · assessed 10 (83%)；4 条 finding（3 Critical）。',
      '组合判断：受控货物 + 制裁目的地 = 硬阻断；硬阻断只来自确定性规则。',
      'Jump to clause 回原文；unchecked_units = 没查到 ≠ 没问题。',
    ],
  },
  {
    id: 'closing',
    title: '收尾：三句诚实边界',
    budget: 50,
    cues: [
      '没查到 ≠ 没问题：覆盖率与 unable_to_assess 就是这件事。',
      '模型不造证据、也不能阻断；出网是用户决定，默认关闭。',
      '边界：非法务意见、非名单筛查、单组织演示。收尾：可复核的审单链路。',
    ],
  },
];

export const PRESENTER_TOTAL_SECONDS = PRESENTER_SECTIONS.reduce(
  (total, section) => total + section.budget,
  0,
);