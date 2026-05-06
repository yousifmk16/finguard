import PagePlaceholder from "@/components/layout/PagePlaceholder";

export default function UsersPage() {
  return (
    <PagePlaceholder
      title="Users"
      taskId="UI-09"
      description="Admin-only user administration. Visibility controlled by RBAC route guard."
    />
  );
}
