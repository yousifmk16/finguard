interface PaginationProps {
  page: number;
  pages: number;
  total: number;
  pageSize: number;
  onPageChange: (next: number) => void;
  disabled?: boolean;
}

export default function Pagination({
  page,
  pages,
  total,
  pageSize,
  onPageChange,
  disabled = false,
}: PaginationProps) {
  const hasResults = total > 0;
  const lastPage = Math.max(pages, 1);
  const start = hasResults ? (page - 1) * pageSize + 1 : 0;
  const end = hasResults ? Math.min(page * pageSize, total) : 0;

  return (
    <nav className="pagination" aria-label="Pagination">
      <span className="pagination__summary">
        {hasResults
          ? `Showing ${start}-${end} of ${total}`
          : "No results"}
      </span>
      <div className="pagination__controls">
        <button
          type="button"
          onClick={() => onPageChange(page - 1)}
          disabled={disabled || page <= 1}
        >
          Previous
        </button>
        <span className="pagination__page">
          Page {page} of {lastPage}
        </span>
        <button
          type="button"
          onClick={() => onPageChange(page + 1)}
          disabled={disabled || page >= lastPage}
        >
          Next
        </button>
      </div>
    </nav>
  );
}
