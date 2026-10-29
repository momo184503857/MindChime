import MarkdownIt from 'markdown-it';
import DOMPurify from 'dompurify';

const markdown = new MarkdownIt({ html: false, linkify: true, breaks: true });
// Referenced media is never fetched automatically. A user may follow the link explicitly.
markdown.renderer.rules.image = (tokens, index) => {
  const token = tokens[index];
  const href = markdown.utils.escapeHtml(token.attrGet('src') || '');
  const label = markdown.utils.escapeHtml(token.content || '查看图片');
  return `<a href="${href}" target="_blank" rel="noopener noreferrer">图片：${label}</a>`;
};
const originalLink = markdown.renderer.rules.link_open;
markdown.renderer.rules.link_open = (tokens, index, options, environment, self) => {
  tokens[index].attrSet('rel', 'noopener noreferrer');
  if (/^https?:\/\//i.test(tokens[index].attrGet('href') || '')) {
    tokens[index].attrSet('target', '_blank');
  }
  return originalLink
    ? originalLink(tokens, index, options, environment, self)
    : self.renderToken(tokens, index, options);
};

export function renderMarkdown(text: string): string {
  return DOMPurify.sanitize(markdown.render(text), {
    ADD_ATTR: ['target', 'rel'],
    FORBID_TAGS: [
      'img',
      'iframe',
      'video',
      'audio',
      'source',
      'object',
      'embed',
      'style',
      'svg',
      'math',
    ],
  });
}
