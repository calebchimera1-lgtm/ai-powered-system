import clsx from 'clsx';

const linkClass = 'text-brand-700 hover:underline';

/** A phone number that dials when tapped. Spaces, dashes and brackets are dropped from the tel: URI. */
export function PhoneLink({ phone, className }: { phone: string; className?: string }) {
  return <a href={`tel:${phone.replace(/[^\d+]/g, '')}`} className={clsx(linkClass, className)}>{phone}</a>;
}

/** An email address that opens the mail app. */
export function EmailLink({ email, className }: { email: string; className?: string }) {
  return <a href={`mailto:${email}`} className={clsx(linkClass, 'break-all', className)}>{email}</a>;
}
