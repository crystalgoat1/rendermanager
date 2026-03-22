interface ConfirmDialogProps {
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  /** Red styling for destructive actions */
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog({
  title,
  message,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  danger = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={onCancel}
      />

      {/* Dialog card */}
      <div className="relative bg-bg-elevated border border-white/10 rounded-2xl shadow-2xl p-6 max-w-sm w-full mx-4 animate-in">
        <h2 className="text-base font-bold mb-2 text-slate-200">{title}</h2>
        <p className="text-sm text-slate-400 leading-relaxed mb-6">{message}</p>

        <div className="flex gap-3 justify-end">
          <button
            onClick={onCancel}
            className="px-4 py-2 rounded-lg border border-white/10 text-slate-400 text-sm font-semibold hover:bg-white/5 hover:text-slate-200 transition-colors"
          >
            {cancelLabel}
          </button>
          <button
            onClick={onConfirm}
            className={
              danger
                ? "px-4 py-2 rounded-lg text-sm font-bold border border-red-500/30 bg-red-500/15 text-red-400 hover:bg-red-500/25 transition-colors"
                : "px-4 py-2 rounded-lg text-sm font-bold gradient-primary text-white hover:opacity-90 transition-opacity"
            }
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
