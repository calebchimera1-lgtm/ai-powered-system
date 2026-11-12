import { useEffect } from 'react';

export const APP_NAME = 'Smart Inventory';

/** Sets the browser tab title to "<page> · Smart Inventory" while the page is shown. */
export function usePageTitle(title: string | null | undefined): void {
  useEffect(() => {
    if (!title) return;
    const previous = document.title;
    document.title = `${title} · ${APP_NAME}`;
    return () => {
      document.title = previous;
    };
  }, [title]);
}
