import { useQuery } from '@tanstack/react-query';
import { Search } from 'lucide-react';
import { forwardRef, useEffect, useState } from 'react';

import { productsApi } from '@/api/catalog';
import type { Product } from '@/api/types';
import { useDebounce } from '@/hooks/useDebounce';
import { formatKES, formatQty } from '@/lib/format';

/**
 * Search box with a results dropdown. Pressing Enter on an exact barcode/SKU (what a USB
 * scanner sends) picks that product straight away.
 */
export const ProductPicker = forwardRef<
  HTMLInputElement,
  {
    onPick: (p: Product) => void;
    onNotFound?: (code: string) => void;
    placeholder?: string;
    showPrice?: boolean;
    label?: string;
    autoFocus?: boolean;
  }
>(function ProductPicker({ onPick, onNotFound, placeholder = 'Scan a barcode or type a product name', showPrice = true, label = 'Find product', autoFocus }, ref) {
  const [text, setText] = useState('');
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const debounced = useDebounce(text.trim(), 200);
  const results = useQuery({
    queryKey: ['products', 'picker', debounced],
    queryFn: () => productsApi.list({ search: debounced, page_size: 8 }),
    enabled: debounced.length >= 2,
  });
  const items = results.data?.items ?? [];
  useEffect(() => setActive(0), [debounced]);

  const pick = (p: Product) => {
    onPick(p);
    setText('');
    setOpen(false);
  };

  const submit = async () => {
    const code = text.trim();
    if (!code) return;
    // Clear immediately, like a till: the next scan (or typing) starts in an empty box
    // even while this code is still being looked up.
    const fallback = open ? items[active] : undefined;
    setText('');
    setOpen(false);
    try {
      const { product } = await productsApi.lookup(code);
      onPick(product);
    } catch {
      if (fallback) onPick(fallback);
      else onNotFound?.(code);
    }
  };

  return (
    <div className="relative">
      <Search className="pointer-events-none absolute left-3 top-1/2 h-5 w-5 -translate-y-1/2 text-gray-400" aria-hidden />
      <input
        ref={ref}
        type="search"
        value={text}
        autoFocus={autoFocus}
        aria-label={label}
        role="combobox"
        aria-expanded={open && items.length > 0}
        aria-controls="product-picker-results"
        placeholder={placeholder}
        onChange={(e) => {
          setText(e.target.value);
          setOpen(true);
        }}
        onBlur={() => window.setTimeout(() => setOpen(false), 150)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            void submit();
          } else if (e.key === 'ArrowDown') {
            e.preventDefault();
            setActive((a) => Math.min(a + 1, items.length - 1));
          } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            setActive((a) => Math.max(a - 1, 0));
          } else if (e.key === 'Escape') {
            setOpen(false);
          }
        }}
        className="h-12 w-full rounded-xl border border-gray-300 bg-white pl-10 pr-3 text-base shadow-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/30"
      />
      {open && items.length > 0 && (
        <ul id="product-picker-results" role="listbox" className="absolute z-30 mt-1 max-h-80 w-full overflow-y-auto rounded-xl border border-gray-200 bg-white py-1 shadow-lg">
          {items.map((p, i) => (
            <li key={p.id} role="option" aria-selected={i === active}>
              <button
                type="button"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => pick(p)}
                className={`flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm ${i === active ? 'bg-brand-50' : 'hover:bg-gray-50'}`}
              >
                <span className="min-w-0">
                  <span className="block truncate font-medium text-gray-900">{p.name}</span>
                  <span className="block text-xs text-gray-500">{p.sku} · {formatQty(p.quantity_on_hand, p.unit_of_measure)} in stock</span>
                </span>
                {showPrice && <span className="shrink-0 tabular-nums text-gray-700">{formatKES(p.selling_price)}</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
});
