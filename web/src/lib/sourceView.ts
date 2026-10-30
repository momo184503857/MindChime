import type { Entity } from './types';

// The source snapshot owns chapter order, including after merges and splits.
export function orderSourceChapters<T extends { source: Entity; chapters: Entity[] }>(
  detail: T,
): T {
  const ids: string[] = detail.source.data.chapter_ids || [];
  const positions = new Map(ids.map((id, index) => [id, index]));
  return {
    ...detail,
    chapters: [...detail.chapters].sort(
      (a, b) =>
        (positions.get(a.id) ?? a.data.order ?? Number.MAX_SAFE_INTEGER) -
        (positions.get(b.id) ?? b.data.order ?? Number.MAX_SAFE_INTEGER),
    ),
  };
}
