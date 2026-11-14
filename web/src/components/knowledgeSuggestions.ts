/**
 * First-use copy and suggested questions (knowledge-onboarding 2A).
 *
 * The questions stay in Chinese because the demo corpus is zh-CN; keeping the exact question text
 * visible in the chip makes it clear what will be sent. Labels in the surrounding UI follow `locale`.
 */

import type { AssistantSelection } from '../api/assistantTypes';

export interface KnowledgeSuggestion {
  id: string;
  /** Both the visible label and the exact question sent to the assistant. */
  label: string;
  question: string;
}

export interface OnboardingCopy {
  summary: string;
  can: string;
  cannot: string;
  how: string;
  showExamples: string;
  hideExamples: string;
}

const COPY: Record<'zh-CN' | 'en', OnboardingCopy> = {
  'zh-CN': {
    summary: '我能问什么？',
    can: '产品与操作 FAQ、贸易规则条款解释、当前文档选中文字的解释。',
    cannot: '不修改正文、不审批、不提交、不联网，也不提供法律结论或代替制裁筛查。',
    how: '问规则时给出名称、版本、法域或适用日期；问文档时先选中一段文字；一次问一个问题。',
    showExamples: 'Show examples',
    hideExamples: 'Hide examples',
  },
  en: {
    summary: 'What can I ask?',
    can: 'Product and operations FAQ, trade-rule explanations, and the selected passage of the document.',
    cannot: 'No edits, approvals, submissions, web access, legal conclusions or sanctions screening.',
    how: 'Name the rule, version, jurisdiction or applicable date; select a passage before asking about the document.',
    showExamples: 'Show examples',
    hideExamples: 'Hide examples',
  },
};

export function onboardingCopy(locale: 'zh-CN' | 'en' = 'en'): OnboardingCopy {
  return COPY[locale] ?? COPY.en;
}

const PRODUCT_QUESTION_ZH = '申请材料需要哪些文件？';
const RULE_QUESTION_ZH = 'URDG 758 第 20 条对索赔有什么要求？';
const PRODUCT_QUESTION_EN = 'What documents are required for the application?';
const RULE_QUESTION_EN = 'What does URDG 758 article 20 require for claims?';

export function suggestionsFor(
  selection: AssistantSelection | null | undefined,
  locale: 'zh-CN' | 'en' = 'en',
): KnowledgeSuggestion[] {
  const english = locale !== 'zh-CN';
  const product = english ? PRODUCT_QUESTION_EN : PRODUCT_QUESTION_ZH;
  const rule = english ? RULE_QUESTION_EN : RULE_QUESTION_ZH;
  if (selection) {
    return [
      {
        id: 'explain-selection',
        label: english ? 'What does this passage mean?' : '这段文字是什么意思？',
        question: english ? 'What does this passage mean?' : '这段文字是什么意思？',
      },
      { id: 'product-materials', label: product, question: product },
      { id: 'rule-urdg', label: rule, question: rule },
    ];
  }
  return [
    {
      id: 'capability-help',
      label: english ? 'What can you do?' : '你能做什么？',
      question: english ? 'What can you do?' : '你能做什么？',
    },
    { id: 'product-materials', label: product, question: product },
    { id: 'rule-urdg', label: rule, question: rule },
  ];
}