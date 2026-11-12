import clsx from 'clsx';
import { Link } from 'react-router-dom';

import { APP_NAME } from '@/hooks/usePageTitle';

/**
 * Site footer. The year is computed, so it never goes stale. Links are only to pages that exist
 * for every signed-in user; signed-out screens get the copyright line alone.
 */
export function AppFooter({ signedIn = true, className }: { signedIn?: boolean; className?: string }) {
  const year = new Date().getFullYear();
  return (
    <footer className={clsx('text-xs text-gray-500', className)}>
      <div className="flex flex-col items-center gap-2 sm:flex-row sm:justify-between">
        <p>© {year} {APP_NAME}. Supermarket management suite.</p>
        {signedIn && (
          <nav aria-label="Footer">
            <ul className="flex gap-4">
              <li><Link to="/account" className="inline-block py-2 hover:text-brand-700 hover:underline">My account</Link></li>
              <li><Link to="/notifications" className="inline-block py-2 hover:text-brand-700 hover:underline">Notifications</Link></li>
            </ul>
          </nav>
        )}
      </div>
    </footer>
  );
}
