import { Navigate, useParams } from 'react-router-dom';
import { CalendarSwitch } from '../components/PlannedItems';
import { PostsPage } from './Content';
import Shoots from '../components/Shoots';

/** Calendar → Posts and Shoots: the lists behind what the calendar shows on each day. */
export default function PlanningPage() {
  const { tab } = useParams();
  if (tab !== 'posts' && tab !== 'shoots') return <Navigate to="/calendar" replace />;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-bold text-white">Calendar</h1>
        <CalendarSwitch current={tab} />
      </div>
      {tab === 'posts' ? <PostsPage /> : <Shoots />}
    </div>
  );
}
