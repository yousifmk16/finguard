import type { ReactNode } from "react";

interface PagePlaceholderProps {
  title: string;
  taskId: string;
  description?: string;
  children?: ReactNode;
}

export default function PagePlaceholder({
  title,
  taskId,
  description,
  children,
}: PagePlaceholderProps) {
  return (
    <section className="page-placeholder">
      <header className="page-placeholder__header">
        <h1>{title}</h1>
        <span className="page-placeholder__task">{taskId}</span>
      </header>
      {description ? <p className="page-placeholder__desc">{description}</p> : null}
      <div className="page-placeholder__body">
        {children ?? <p>This screen will be implemented in {taskId}.</p>}
      </div>
    </section>
  );
}
