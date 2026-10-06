/**
 * A custom line, described from the CUSTOM / OTHER matrix (FR-9's custom tab,
 * requirements 5.4 and 5.6). The matrix exists so an estimator can describe a
 * line past the stock list precisely - keying included, which sits in the lock
 * options - not so anything can price one: the cost is the estimator's.
 */
export interface CustomChoice {
  item: string;
  manufacturer?: string;
  function?: string;
  backset?: string;
  finish?: string;
  lever?: string;
  keyway?: string;
  strike?: string;
  electrified?: string[];
  preps?: string[];
}

/** The matrix's option lists, as the reference API returns them. */
export interface CustomOtherMatrix {
  functions?: string[];
  backsets?: string[];
  finishes?: string[];
  levers?: string[];
  keyways?: string[];
  strikes?: string[];
  electrified?: string[];
  preps?: string[];
  keying_note?: string;
}

/** "HAGER LOCKSET, STOREROOM FUNCTION, 2-3/4" BACKSET, US26D, WITHNELL LEVER, SFIC". */
export function customDescription(choice: CustomChoice): string {
  const head = [choice.manufacturer, choice.item].map((part) => part?.trim()).filter(Boolean).join(" ");
  const lever = choice.lever?.trim();
  const options = [
    choice.function && `${choice.function} function`,
    choice.backset && `${choice.backset.replace(/\s*\(standard\)/i, "")} backset`,
    choice.finish,
    lever && (/knob/i.test(lever) ? lever : `${lever} lever`),
    choice.keyway,
    choice.strike && (/strike/i.test(choice.strike) ? choice.strike : `${choice.strike} strike`),
    ...(choice.electrified ?? []),
    ...(choice.preps ?? []),
  ].filter((part): part is string => Boolean(part && part.trim()));
  return [head, ...options].join(", ").toUpperCase();
}
