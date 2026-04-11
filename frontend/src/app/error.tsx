"use client";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="flex items-center justify-center min-h-[60vh]">
      <div className="bg-card border border-line rounded-xl p-8 max-w-md text-center">
        <h2 className="text-lg font-semibold text-ink mb-2">
          Something went wrong
        </h2>
        <p className="text-sm text-mute mb-4">{error.message}</p>
        <button
          onClick={reset}
          className="px-4 py-2 text-sm bg-accent text-bg font-semibold rounded-lg hover:brightness-110 transition-all"
        >
          Try again
        </button>
      </div>
    </div>
  );
}
