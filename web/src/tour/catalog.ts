/** The tour catalog offered by the launcher and by `?tour=<id>` deep links. */

import type { Tour } from './types';
import { APPROVAL_TOUR } from './tours/approval';
import { AUDIT_TOUR } from './tours/audit';
import { AUTOMATION_TOUR } from './tours/automation';
import { CORE_TOUR } from './tours/core';
import { LEGAL_TOUR } from './tours/legal';
import {
  LIFECYCLE_APPLICANT,
  LIFECYCLE_FIRST,
  LIFECYCLE_SECOND,
} from './tours/lifecycle';

export const LIFECYCLE_IDS = [
  'lifecycle-applicant',
  'lifecycle-first',
  'lifecycle-second',
] as const;

export const TOURS: Tour[] = [
  CORE_TOUR,
  LIFECYCLE_APPLICANT,
  LIFECYCLE_FIRST,
  LIFECYCLE_SECOND,
  AUDIT_TOUR,
  LEGAL_TOUR,
  APPROVAL_TOUR,
  AUTOMATION_TOUR,
];