// Pure, measured wrapping. No ellipsis, slicing away words, or fixed-length caps.
export function wrapText(text, size, width, measure) {
  const words = String(text).trim().split(/\s+/u).filter(Boolean);
  const lines = []; let line = '';
  for (const word of words) {
    const candidate = line ? `${line} ${word}` : word;
    if (measure(candidate, size) <= width) { line = candidate; continue; }
    if (line) { lines.push(line); line = ''; }
    if (measure(word, size) <= width) { line = word; continue; }
    // Break overlong URLs / unspaced scripts by grapheme, preserving all content.
    const segments = [...new Intl.Segmenter(undefined, {granularity:'grapheme'}).segment(word)].map(x => x.segment);
    for (const char of segments) {
      if (line && measure(line + char, size) > width) { lines.push(line); line = ''; }
      line += char;
    }
  }
  if (line) lines.push(line);
  return lines;
}
export function fitText(text, width, height, maxSize, maxLines, measure) {
  let low = 0.1, high = maxSize;
  for (let i = 0; i < 22; i++) {
    const size = (low + high) / 2;
    const lines = wrapText(text, size, width, measure);
    const fits = lines.length <= maxLines && lines.length * size * 1.08 <= height && lines.every(l => measure(l,size) <= width + .01);
    if (fits) low = size; else high = size;
  }
  return {size: low, lines: wrapText(text, low, width, measure)};
}
