type SearchKeys = { names: readonly string[]; descriptions?: readonly string[] };

const WORD_CHAR = /[\p{L}\p{N}]/u;
const UNSPACED = /[\p{scx=Han}\p{scx=Hira}\p{scx=Kana}\p{scx=Hang}]/u;
const UPPER = /\p{Lu}/u;
const LOWER = /\p{Ll}/u;
const PRINTABLE_ASCII = /^[\x20-\x7e]*$/;
const DIACRITIC = /[\u0300-\u036f]/gu;
const STROKED: Record<string, string> = {
  ø: 'o',
  Ø: 'O',
  ł: 'l',
  Ł: 'L',
  đ: 'd',
  Đ: 'D',
  ð: 'd',
  Ð: 'D',
  ı: 'i',
  ħ: 'h',
  Ħ: 'H',
  ŧ: 't',
  Ŧ: 'T',
};
const STROKED_CHAR = /[øØłŁđĐðÐıħĦŧŦ]/gu;

function strip(value: string): string {
  if (PRINTABLE_ASCII.test(value)) return value;
  return value
    .normalize('NFKD')
    .replace(DIACRITIC, '')
    .normalize('NFKC')
    .replace(STROKED_CHAR, (char) => STROKED[char] ?? char);
}

function prepare(name: string) {
  const stripped = strip(name);
  const tails: string[] = [];
  let previous = '';
  let offset = 0;
  for (const char of stripped) {
    if (
      !WORD_CHAR.test(previous) ||
      UNSPACED.test(char) ||
      (UPPER.test(char) && LOWER.test(previous))
    ) {
      tails.push(stripped.slice(offset).toLowerCase());
    }
    previous = char;
    offset += char.length;
  }
  return { folded: stripped.toLowerCase(), tails };
}

function subsequence(term: string, text: string): number {
  if (text.codePointAt(0) !== term.codePointAt(0)) return 0;
  let at = 0;
  for (const char of term) {
    at = text.indexOf(char, at);
    if (at === -1) return 0;
    at += char.length;
  }
  return 2 + Math.min(0.99, term.length / at);
}

function termScore(term: string, names: ReturnType<typeof prepare>[], descriptions: string[]) {
  let best = 0;
  for (const name of names) {
    const at = name.folded.indexOf(term);
    if (at === 0) return 4;
    if (at > 0) best = 3;
    if (best >= 3) continue;
    for (const tail of name.tails) best = Math.max(best, subsequence(term, tail));
  }
  return best || Number(descriptions.some((text) => text.includes(term)));
}

export function indexModelCatalog<T>(items: readonly T[], keys: (item: T) => SearchKeys) {
  const indexed = items.map((item) => {
    const { names, descriptions = [] } = keys(item);
    return {
      item,
      names: names.filter(Boolean).map(prepare),
      descriptions: descriptions.filter(Boolean).map((text) => strip(text).toLowerCase()),
    };
  });

  return (query: string): readonly T[] => {
    const terms = query
      .trim()
      .split(/\s+/u)
      .map((term) => strip(term).toLowerCase())
      .filter(Boolean);
    if (!terms.length) return items;
    const matches: { item: T; score: number; index: number }[] = [];
    indexed.forEach(({ item, names, descriptions }, index) => {
      let score = 0;
      for (const term of terms) {
        const hit = termScore(term, names, descriptions);
        if (!hit) return;
        score += hit;
      }
      matches.push({ item, score, index });
    });
    return matches
      .sort((left, right) => right.score - left.score || left.index - right.index)
      .map(({ item }) => item);
  };
}
