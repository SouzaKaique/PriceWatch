import { centsToInput, formatCents, parseBRL } from './money';

describe('money helpers', () => {
  it('parses Brazilian formats', () => {
    expect(parseBRL('1.299,90')).toBe(129990);
    expect(parseBRL('R$ 750')).toBe(75000);
    expect(parseBRL('749.9')).toBe(74990);
    expect(parseBRL('')).toBeNull();
    expect(parseBRL('abc')).toBeNaN();
  });

  it('formats cents', () => {
    expect(formatCents(74990).replace(/\s/g, ' ')).toBe('R$ 749,90');
    expect(formatCents(null)).toBe('—');
    expect(centsToInput(129990)).toBe('1299,90');
  });
});
