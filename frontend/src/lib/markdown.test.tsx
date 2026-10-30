import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Markdown } from './markdown';

describe('Markdown de los agentes', () => {
  it('las citas del panel son enlaces; cualquier otra URL queda como texto', () => {
    render(<Markdown text={'Hay 3 [ver en el panel](#/secops/gestion), [sitio](https://evil.example) y [x](javascript:alert(1))'} />);
    expect(screen.getByRole('link', { name: 'ver en el panel' })).toHaveAttribute('href', '#/secops/gestion');
    expect(screen.queryByRole('link', { name: 'sitio' })).toBeNull();
    expect(screen.getByText(/sitio/)).toBeInTheDocument();
    expect(screen.getAllByRole('link')).toHaveLength(1);
  });
});
