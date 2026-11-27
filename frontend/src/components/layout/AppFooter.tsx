import clsx from 'clsx';
import { Link } from 'react-router-dom';

import { APP_NAME } from '@/hooks/usePageTitle';

/**
 * Site footer. The year is computed, so it never goes stale. The privacy notice and terms of
 * use are linked everywhere, including the sign-in screen.
 */
export function AppFooter({ signedIn = true, className }: { signedIn?: boolean; className?: string }) {
  const year = new Date().getFullYear();
  return (
    <footer className={clsx('text-xs text-gray-500', className)}>
      <div className="flex flex-col items-center gap-2 sm:flex-row sm:justify-between">
        <p>© {year} {APP_NAME}. Supermarket management suite.</p>
        <nav aria-label="Footer">
          <ul className="flex flex-wrap justify-center gap-x-4">
            {signedIn && <li><Link to="/account" className="inline-block py-2 hover:text-brand-700 hover:underline">My account</Link></li>}
            <li><Link to="/privacy" className="inline-block py-2 hover:text-brand-700 hover:underline">Privacy notice</Link></li>
            <li><Link to="/terms" className="inline-block py-2 hover:text-brand-700 hover:underline">Terms of use</Link></li>
          </ul>
        </nav>
      </div>
    </footer>
  );
}
