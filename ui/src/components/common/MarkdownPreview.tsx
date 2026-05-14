type MarkdownPreviewProps = {
  text: string;
  emptyText?: string;
  className?: string;
};

type Block =
  | { type: 'heading'; level: number; text: string; key: string }
  | { type: 'paragraph'; text: string; key: string }
  | { type: 'list'; ordered: boolean; items: string[]; key: string }
  | { type: 'code'; text: string; key: string }
  | { type: 'table'; rows: string[][]; key: string };

function parseInline(text: string) {
  const parts = text.split(/(`[^`]+`|\*\*[^*]+\*\*)/g).filter(Boolean);
  return parts.map((part, index) => {
    if (part.startsWith('`') && part.endsWith('`')) {
      return <code key={index}>{part.slice(1, -1)}</code>;
    }
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={index}>{part.slice(2, -2)}</strong>;
    }
    return <span key={index}>{part}</span>;
  });
}

function splitTableRow(line: string) {
  return line
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((cell) => cell.trim());
}

function isSeparatorRow(line: string) {
  return /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line);
}

function parseMarkdown(text: string): Block[] {
  const lines = text.replace(/\r\n/g, '\n').split('\n');
  const blocks: Block[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) {
      index += 1;
      continue;
    }

    if (line.trim().startsWith('```')) {
      const key = `code-${index}`;
      const codeLines: string[] = [];
      index += 1;
      while (index < lines.length && !lines[index].trim().startsWith('```')) {
        codeLines.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) index += 1;
      blocks.push({ type: 'code', text: codeLines.join('\n'), key });
      continue;
    }

    const heading = /^(#{1,4})\s+(.+)$/.exec(line);
    if (heading) {
      blocks.push({ type: 'heading', level: heading[1].length, text: heading[2].trim(), key: `heading-${index}` });
      index += 1;
      continue;
    }

    if (line.includes('|') && index + 1 < lines.length && isSeparatorRow(lines[index + 1])) {
      const key = `table-${index}`;
      const rows = [splitTableRow(line)];
      index += 2;
      while (index < lines.length && lines[index].includes('|') && lines[index].trim()) {
        rows.push(splitTableRow(lines[index]));
        index += 1;
      }
      blocks.push({ type: 'table', rows, key });
      continue;
    }

    const listMatch = /^\s*(([-*])|(\d+\.))\s+(.+)$/.exec(line);
    if (listMatch) {
      const key = `list-${index}`;
      const ordered = Boolean(listMatch[3]);
      const items: string[] = [];
      while (index < lines.length) {
        const item = /^\s*(([-*])|(\d+\.))\s+(.+)$/.exec(lines[index]);
        if (!item || Boolean(item[3]) !== ordered) break;
        items.push(item[4].trim());
        index += 1;
      }
      blocks.push({ type: 'list', ordered, items, key });
      continue;
    }

    const paragraphLines = [line.trim()];
    index += 1;
    while (index < lines.length && lines[index].trim() && !/^(#{1,4})\s+/.test(lines[index]) && !lines[index].trim().startsWith('```') && !/^\s*(([-*])|(\d+\.))\s+/.test(lines[index])) {
      if (lines[index].includes('|') && index + 1 < lines.length && isSeparatorRow(lines[index + 1])) break;
      paragraphLines.push(lines[index].trim());
      index += 1;
    }
    blocks.push({ type: 'paragraph', text: paragraphLines.join(' '), key: `paragraph-${index}` });
  }

  return blocks;
}

export function MarkdownPreview({ text, emptyText = 'No preview available', className = '' }: MarkdownPreviewProps) {
  const blocks = parseMarkdown(text.trim());
  if (!blocks.length) {
    return <div className={`markdown-preview ${className}`.trim()}><p className="empty-state">{emptyText}</p></div>;
  }

  return (
    <div className={`markdown-preview ${className}`.trim()}>
      {blocks.map((block) => {
        if (block.type === 'heading') {
          if (block.level === 1) return <h2 key={block.key}>{parseInline(block.text)}</h2>;
          if (block.level === 2) return <h3 key={block.key}>{parseInline(block.text)}</h3>;
          if (block.level === 3) return <h4 key={block.key}>{parseInline(block.text)}</h4>;
          return <h5 key={block.key}>{parseInline(block.text)}</h5>;
        }
        if (block.type === 'paragraph') {
          return <p key={block.key}>{parseInline(block.text)}</p>;
        }
        if (block.type === 'code') {
          return <pre key={block.key}><code>{block.text}</code></pre>;
        }
        if (block.type === 'table') {
          const [header, ...rows] = block.rows;
          return (
            <div className="markdown-table-wrap" key={block.key}>
              <table>
                <thead><tr>{header.map((cell, index) => <th key={index}>{parseInline(cell)}</th>)}</tr></thead>
                <tbody>{rows.map((row, rowIndex) => <tr key={rowIndex}>{row.map((cell, cellIndex) => <td key={cellIndex}>{parseInline(cell)}</td>)}</tr>)}</tbody>
              </table>
            </div>
          );
        }
        const ListTag = block.ordered ? 'ol' : 'ul';
        return <ListTag key={block.key}>{block.items.map((item, index) => <li key={index}>{parseInline(item)}</li>)}</ListTag>;
      })}
    </div>
  );
}
