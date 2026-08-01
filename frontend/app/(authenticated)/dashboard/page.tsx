import type { Metadata } from "next";
import { DashboardScreen } from "../../components/dashboard-screen";

export const metadata: Metadata = {
  title: "Dashboard — Graphify",
  description: "Your recently graphed projects.",
};

export default function DashboardPage() {
  return <DashboardScreen />;
}
