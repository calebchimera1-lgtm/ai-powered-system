import { useMutation, useQueryClient } from '@tanstack/react-query';

import { notificationsApi } from '@/api/analytics';
import { useToast } from '@/components/ui/Toast';
import { errorMessage } from '@/lib/errors';

/** Marks the given notifications (or all, when called with no ids) as read and refreshes every notification view. */
export function useMarkRead() {
  const qc = useQueryClient();
  const toast = useToast();
  return useMutation({
    mutationFn: (ids?: number[]) => notificationsApi.markRead(ids),
    onError: (err) => toast.error('Could not mark as read', errorMessage(err)),
    onSettled: () => qc.invalidateQueries({ queryKey: ['notifications'] }),
  });
}
