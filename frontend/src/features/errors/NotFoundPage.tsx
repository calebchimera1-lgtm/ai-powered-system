import { Compass } from 'lucide-react';
import { Link, useLocation } from 'react-router-dom';

import { Card } from '@/components/ui/Card';
import { usePageTitle } from '@/hooks/usePageTitle';

/** Shown for any address inside the app that doesn't match a route. */
export function NotFoundPage() {
  usePageTitle('Page not found');
  const { pathname } = useLocation();
  return (
    <Card className="mx-auto max-w-lg">
      <div className="flex flex-col items-center px-2 py-8 text-center">
        <div className="mb-4 rounded-full bg-brand-50 p-3 text-brand-700">
          <Compass className="h-7 w-7" aria-hidden />
        </div>
        <p className="text-sm font-semibold text-brand-700">Error 404</p>
        <h1 className="mt-1 text-xl font-semibold text-gray-900">Page not found</h1>
        <p className="mt-2 text-sm text-gray-600">
          There is no page at <code className="break-all rounded bg-gray-100 px-1 py-0.5 text-gray-800">{pathname}</code>.
          It may have been moved, or the link may be mistyped.
        </p>
        <div className="mt-6 flex flex-wrap justify-center gap-3">
          <Link to="/" className="inline-flex items-center rounded-lg bg-brand-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-brand-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600">
            Go to home
          </Link>
          <button type="button" onClick={() => window.history.back()} className="inline-flex items-center rounded-lg border border-gray-300 bg-white px-4 py-2.5 text-sm font-medium text-gray-700 hover:bg-gray-50">
            Go back
          </button>
        </div>
      </div>
    </Card>
  );
}
