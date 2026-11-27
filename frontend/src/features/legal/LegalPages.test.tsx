import { screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as client from '@/api/client';
import { renderWithProviders } from '@/test/utils';

import { PrivacyPage, TermsPage } from './LegalPages';

const info = {
  store_name: 'Smart Supermarket', store_address: 'Nairobi, Kenya', store_phone: '+254700000000',
  store_kra_pin: 'P051234567X', privacy_contact: 'privacy@shop.example', return_policy: 'Within 7 days with the receipt.',
  ai_assistant: true, mpesa_prompts: true, document_archive: false,
};

describe('Legal pages', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(client.api, 'get').mockResolvedValue({ data: info });
  });

  it('privacy notice names the shop, the contact and every outside service in use', async () => {
    renderWithProviders(<PrivacyPage />);
    expect(await screen.findByText('privacy@shop.example')).toBeInTheDocument();
    expect(screen.getByText('Smart Supermarket')).toBeInTheDocument();
    expect(screen.getByText('Anthropic')).toBeInTheDocument();
    expect(screen.getByText('Safaricom')).toBeInTheDocument();
    expect(screen.getByText(/no cookie consent banner is needed/i)).toBeInTheDocument();
    expect(screen.getByText(/odpc\.go\.ke/)).toBeInTheDocument();
  });

  it('terms of use show the return policy and the AI disclaimer', async () => {
    renderWithProviders(<TermsPage />);
    expect(await screen.findByText(/Within 7 days with the receipt/)).toBeInTheDocument();
    expect(screen.getByText(/can make mistakes/)).toBeInTheDocument();
  });
});
