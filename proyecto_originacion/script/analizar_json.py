import json
import os
import sys

def analizar_json(ruta_json):
    """Analiza la estructura de un archivo JSON y muestra sus atributos principales."""
    try:
        with open(ruta_json, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        print(f"Analizando archivo: {ruta_json}")
        print("=" * 50)
        
        # Mostrar las claves de primer nivel
        print("Claves de primer nivel:")
        for key in data.keys():
            print(f"- {key}")
        
        # Analizar documento si existe
        if 'document' in data:
            print("\nEstructura del documento:")
            doc = data['document']
            for key in doc.keys():
                if key == 'entities':
                    entities = doc['entities']
                    print(f"- entities: {len(entities)} entidades encontradas")
                    
                    # Mostrar tipos de entidades únicos
                    entity_types = set()
                    for entity in entities:
                        if 'type' in entity:
                            entity_types.add(entity['type'])
                    
                    print(f"  Tipos de entidades: {sorted(list(entity_types))}")
                    
                    # Mostrar ejemplo de una entidad
                    if entities:
                        print("\nEjemplo de entidad:")
                        entity_example = entities[0]
                        for k, v in entity_example.items():
                            if isinstance(v, dict) or isinstance(v, list):
                                print(f"  - {k}: {type(v)}")
                            else:
                                print(f"  - {k}: {v}")
                else:
                    value = doc[key]
                    if isinstance(value, dict) or isinstance(value, list):
                        print(f"- {key}: {type(value)}")
                    else:
                        print(f"- {key}: {value}")
        
        # Verificar si hay detectado texto
        if 'text' in data.get('document', {}):
            texto = data['document']['text']
            print(f"\nExtracto de texto (primeros 200 caracteres):")
            print(texto[:200] + "..." if len(texto) > 200 else texto)
        
        print("\nEstructura analizada correctamente.")
        
    except Exception as e:
        print(f"Error al analizar el archivo JSON: {e}")
        return False
    
    return True

if __name__ == "__main__":
    # Usar la ruta especificada o la predeterminada
    ruta_default = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "muestra.json")
    ruta_json = sys.argv[1] if len(sys.argv) > 1 else ruta_default
    
    if not os.path.exists(ruta_json):
        print(f"El archivo {ruta_json} no existe.")
    else:
        analizar_json(ruta_json) 