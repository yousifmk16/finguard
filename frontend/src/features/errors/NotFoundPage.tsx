import { Link } from "react-router-dom";

export default function NotFoundPage() {
  return (
    <div className="error-page">
      <h1>404 - Not Found</h1>
      <p>The page you requested does not exist.</p>
      <Link to="/dashboard">Return to dashboard</Link>
    </div>
  );
}
