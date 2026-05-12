import { Navigate, Route, Routes } from "react-router-dom";
import AppLayout from "@/components/layout/AppLayout";
import ProtectedRoute from "@/components/auth/ProtectedRoute";
import AdminRoute from "@/components/auth/AdminRoute";
import LoginPage from "@/features/auth/LoginPage";
import DashboardPage from "@/features/dashboard/DashboardPage";
import AnomaliesListPage from "@/features/anomalies/AnomaliesListPage";
import AnomalyDetailPage from "@/features/anomalies/AnomalyDetailPage";
import AlertCenterPage from "@/features/alerts/AlertCenterPage";
import PoliciesPage from "@/features/policies/PoliciesPage";
import UsersPage from "@/features/users/UsersPage";
import SettingsPage from "@/features/settings/SettingsPage";
import ModelTrainingPage from "@/features/training/ModelTrainingPage";
import ForbiddenPage from "@/features/errors/ForbiddenPage";
import NotFoundPage from "@/features/errors/NotFoundPage";

export default function AppRouter() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/forbidden" element={<ForbiddenPage />} />

      <Route
        element={
          <ProtectedRoute>
            <AppLayout />
          </ProtectedRoute>
        }
      >
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/anomalies" element={<AnomaliesListPage />} />
        <Route path="/anomalies/:anomalyId" element={<AnomalyDetailPage />} />
        <Route path="/alerts" element={<AlertCenterPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/policies" element={<PoliciesPage />} />
        <Route
          path="/users"
          element={
            <AdminRoute>
              <UsersPage />
            </AdminRoute>
          }
        />
        <Route path="/datagen" element={<Navigate to="/model-training" replace />} />
        <Route
          path="/model-training"
          element={
            <AdminRoute>
              <ModelTrainingPage />
            </AdminRoute>
          }
        />
      </Route>

      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}
