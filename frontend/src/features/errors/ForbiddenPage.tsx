import { Link } from "react-router-dom";

export default function ForbiddenPage() {
  return (
    <div className="error-page">
      <h1>403 - Forbidden</h1>
      <p>You do not have permission to access this area.</p>
      <Link to="/dashboard">Return to dashboard</Link>
    </div>
  );
}
