import { Component, type ErrorInfo, type ReactNode } from 'react';

/**
 * Barrera de error por sección.
 *
 * Un `undefined.toFixed()` en una celda de tabla tumbaba el árbol entero de
 * React y la pestaña quedaba en blanco, sin un solo mensaje para el usuario:
 * el fallo solo era visible abriendo la consola del navegador. Pasó de verdad
 * con la tabla de showback, que leía un campo que el backend había dejado de
 * enviar.
 *
 * Envolviendo cada pestaña, un fallo así degrada a un aviso legible dentro de
 * su sección y el resto de la plataforma sigue en pie. No sustituye a corregir
 * el error —el aviso dice cuál fue—, pero evita que un campo renombrado en el
 * backend deje sin herramienta a quien la está usando.
 */
interface Props {
  children: ReactNode;
  /** Nombre de la sección, para que el aviso diga qué falló. */
  name: string;
}

interface State {
  error: Error | null;
}

export class SectionBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Se conserva la traza en consola: el aviso de la interfaz es para el
    // usuario, esto es para quien tenga que arreglarlo.
    console.error(`[${this.props.name}] fallo al renderizar`, error, info.componentStack);
  }

  /** Permite reintentar sin recargar toda la aplicación. */
  private reintentar = () => this.setState({ error: null });

  render() {
    if (!this.state.error) return this.props.children;

    return (
      <div className="card">
        <div className="empty">
          <strong>No se pudo mostrar la sección «{this.props.name}»</strong>
          <span>El resto de la plataforma sigue funcionando. Detalle técnico: <code>{this.state.error.message}</code></span>
          <button className="btn btn-sm" onClick={this.reintentar}>Reintentar</button>
        </div>
      </div>
    );
  }
}
