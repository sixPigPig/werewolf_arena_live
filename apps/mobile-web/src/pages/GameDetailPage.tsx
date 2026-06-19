import { Navigate, useParams } from "react-router-dom";

export function GameDetailPage() {
  const { gameId } = useParams();

  return <Navigate replace to={`/games/${gameId ?? ""}/replay`} />;
}
