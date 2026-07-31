import Image from "next/image";

type BrandLockupProps = {
  className?: string;
  priority?: boolean;
};

export function BrandLockup({
  className = "brand-lockup",
  priority = false,
}: BrandLockupProps) {
  return (
    <div className={className} aria-label="Graphify">
      <Image
        className="brand-lockup-mark"
        src="/graphify-mark.png"
        alt=""
        width={28}
        height={28}
        priority={priority}
      />
      graphify
    </div>
  );
}
