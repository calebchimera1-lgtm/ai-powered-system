import { ScanLine } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';

import { Alert } from './Alert';
import { Button } from './Button';
import { Modal } from './Modal';

/**
 * Camera barcode scanner (EAN-13/8, UPC, Code 128, QR...) using ZXing.
 *
 * USB/Bluetooth scanners don't need this: they type the code into the focused input
 * and press Enter. The camera requires HTTPS or http://localhost.
 */
export function BarcodeScannerModal({
  open,
  onClose,
  onDetected,
}: {
  open: boolean;
  onClose: () => void;
  onDetected: (code: string) => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setError(null);
    let stop: (() => void) | undefined;
    let cancelled = false;

    (async () => {
      if (!navigator.mediaDevices?.getUserMedia) {
        setError(
          'This browser cannot use the camera here. The camera needs a secure (https) connection; you can still type the code.',
        );
        return;
      }
      try {
        const { BrowserMultiFormatReader } = await import('@zxing/browser');
        if (cancelled || !videoRef.current) return;
        const reader = new BrowserMultiFormatReader();
        const controls = await reader.decodeFromConstraints(
          { video: { facingMode: { ideal: 'environment' } } },
          videoRef.current,
          (result) => {
            if (result) {
              controls.stop();
              navigator.vibrate?.(80);
              onDetected(result.getText());
            }
          },
        );
        stop = () => controls.stop();
        if (cancelled) stop();
      } catch (err) {
        const name = (err as { name?: string })?.name;
        setError(
          name === 'NotAllowedError'
            ? 'Camera permission was refused. Allow camera access in the browser settings, or type the code.'
            : name === 'NotFoundError'
              ? 'No camera was found on this device.'
              : 'The camera could not be started.',
        );
      }
    })();

    return () => {
      cancelled = true;
      stop?.();
    };
  }, [open, onDetected]);

  return (
    <Modal open={open} onClose={onClose} title="Scan a barcode" description="Point the camera at the barcode." size="sm"
      footer={<Button variant="secondary" onClick={onClose}>Cancel</Button>}
    >
      {error ? (
        <Alert tone="warning">{error}</Alert>
      ) : (
        <div className="relative overflow-hidden rounded-xl bg-gray-900">
          <video ref={videoRef} className="aspect-[4/3] w-full object-cover" muted playsInline />
          <div className="pointer-events-none absolute inset-x-8 top-1/2 h-0.5 -translate-y-1/2 bg-red-500/80 shadow-[0_0_8px_rgba(239,68,68,0.8)]" />
        </div>
      )}
    </Modal>
  );
}

export function ScanButton({ onDetected, label = 'Scan' }: { onDetected: (code: string) => void; label?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button
        variant="secondary"
        icon={<ScanLine className="h-4 w-4" />}
        onClick={() => setOpen(true)}
        aria-label="Scan barcode with camera"
      >
        <span className="hidden sm:inline">{label}</span>
      </Button>
      <BarcodeScannerModal
        open={open}
        onClose={() => setOpen(false)}
        onDetected={(code) => {
          setOpen(false);
          onDetected(code);
        }}
      />
    </>
  );
}
