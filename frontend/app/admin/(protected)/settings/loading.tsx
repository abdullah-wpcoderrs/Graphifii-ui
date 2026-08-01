import { Spinner } from "../../../components/ui";

export default function AdminSettingsLoading() {
  return (
    <div className="page-content page-content-centered" aria-busy="true">
      <Spinner size="lg" label="Loading admin settings" />
    </div>
  );
}
