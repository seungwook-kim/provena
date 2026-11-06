import logoAsset from '../assets/provena-logo-a.png'

export default function Logo({ className = '' }) {
  return <img className={`provena-logo ${className}`.trim()} src={logoAsset} alt="Provena" />
}
