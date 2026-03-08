from sqlalchemy import Column, String, Index, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class Word(Base):
    __tablename__ = "words"

    renshuu_id = Column(String, primary_key=True)
    japanese = Column(String, nullable=False)
    reading = Column(String, nullable=False)
    jmdict_id = Column(String, nullable=True)

    # Relationships
    list_memberships = relationship("ListMembership", back_populates="word", cascade="all, delete-orphan")

    # Indexes
    __table_args__ = (
        Index("idx_japanese_reading", "japanese", "reading"),
        Index("idx_jmdict_id", "jmdict_id"),
    )

    def __repr__(self):
        return f"<Word(renshuu_id={self.renshuu_id}, japanese={self.japanese}, reading={self.reading})>"


class ListMembership(Base):
    __tablename__ = "list_memberships"

    list_id = Column(String, primary_key=True)
    renshuu_id = Column(String, ForeignKey("words.renshuu_id", ondelete="CASCADE"), primary_key=True)

    # Relationships
    word = relationship("Word", back_populates="list_memberships")

    # Indexes
    __table_args__ = (
        Index("idx_list_id", "list_id"),
    )

    def __repr__(self):
        return f"<ListMembership(list_id={self.list_id}, renshuu_id={self.renshuu_id})>"

